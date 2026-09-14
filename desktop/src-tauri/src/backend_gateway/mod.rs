//! 后端网关（方案 §8）。
//!
//! 职责：按 connection_id 解析地址（前端不传任意 URL）、注入凭据、设定超时、
//! 归一化错误。G0 覆盖 REST 与 /health、/auth；SSE/WS 在 G1/G2 增量。

use crate::connections::ConnectionStore;
use crate::credentials;
use crate::error::{ClientError, CmdResult, ErrorKind};
use serde::{Deserialize, Serialize};
use std::time::Duration;

/// 受控 API 操作枚举（方案 §8.2）——替代任意 method+URL。
/// 内部标签 `op`，与前端 `contracts/ipc.ts` 的 ApiOperation 对齐。
#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "op")]
pub enum ApiOperation {
    #[serde(rename = "health")]
    Health,
    #[serde(rename = "me")]
    Me,
    #[serde(rename = "sessions.list")]
    SessionsList {
        #[serde(default)]
        limit: Option<u32>,
    },
    #[serde(rename = "sessions.create")]
    SessionsCreate {
        #[serde(default)]
        title: Option<String>,
    },
    #[serde(rename = "sessions.messages")]
    SessionsMessages {
        session_id: String,
        #[serde(default)]
        limit: Option<u32>,
    },
    #[serde(rename = "approvals.list")]
    ApprovalsList,
    #[serde(rename = "budget.get")]
    BudgetGet { session_id: String },
}

enum Method {
    Get,
    Post,
}

struct Resolved {
    method: Method,
    path: String,
    body: Option<serde_json::Value>,
    /// 是否需要鉴权（health 为公开路由）。
    auth: bool,
}

impl ApiOperation {
    fn resolve(&self) -> Resolved {
        match self {
            ApiOperation::Health => Resolved { method: Method::Get, path: "/health".into(), body: None, auth: false },
            ApiOperation::Me => Resolved { method: Method::Get, path: "/auth/me".into(), body: None, auth: true },
            ApiOperation::SessionsList { limit } => Resolved {
                method: Method::Get,
                path: format!("/sessions?limit={}", limit.unwrap_or(50)),
                body: None,
                auth: true,
            },
            ApiOperation::SessionsCreate { title } => Resolved {
                method: Method::Post,
                path: "/sessions".into(),
                body: Some(serde_json::json!({ "title": title.clone().unwrap_or_else(|| "新会话".into()) })),
                auth: true,
            },
            ApiOperation::SessionsMessages { session_id, limit } => Resolved {
                method: Method::Get,
                path: format!("/sessions/{session_id}/messages?limit={}", limit.unwrap_or(200)),
                body: None,
                auth: true,
            },
            ApiOperation::ApprovalsList => Resolved {
                method: Method::Get,
                path: "/chat/approvals".into(),
                body: None,
                auth: true,
            },
            ApiOperation::BudgetGet { session_id } => Resolved {
                method: Method::Get,
                path: format!("/budget/{session_id}"),
                body: None,
                auth: true,
            },
        }
    }
}

fn client() -> CmdResult<reqwest::Client> {
    reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(6))
        .timeout(Duration::from_secs(30))
        .user_agent("Vanta-Desktop/0.0.0")
        .build()
        .map_err(ClientError::from)
}

/// /health 响应（后端当前形状；capabilities 为未来增量，缺省即视为全 false）。
#[derive(Debug, Deserialize)]
struct HealthBody {
    #[allow(dead_code)]
    status: String,
    #[serde(default)]
    version: String,
    #[serde(default)]
    worker_model: String,
    #[serde(default)]
    capabilities: Option<ServerCapabilities>,
    #[serde(default)]
    api_version: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ServerCapabilities {
    #[serde(default)]
    pub api_version: Option<String>,
    #[serde(default)]
    pub run_snapshot: bool,
    #[serde(default)]
    pub event_replay: bool,
    #[serde(default)]
    pub run_cancel: bool,
    #[serde(default)]
    pub artifact_export: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HealthResult {
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub server_version: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub worker_model: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub capabilities: Option<ServerCapabilities>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub latency_ms: Option<u64>,
}

/// GET /health —— 探活 + 能力协商（连接未激活时也可用 base_url 直探）。
pub async fn health(base_url: &str) -> CmdResult<HealthResult> {
    let start = std::time::Instant::now();
    let resp = client()?
        .get(format!("{base_url}/health"))
        .send()
        .await
        .map_err(ClientError::from)?;
    let latency = start.elapsed().as_millis() as u64;
    if !resp.status().is_success() {
        return Err(map_status(resp.status()));
    }
    let body: HealthBody = resp.json().await.map_err(ClientError::from)?;
    let mut caps = body.capabilities.unwrap_or_default();
    if caps.api_version.is_none() {
        caps.api_version = body.api_version;
    }
    Ok(HealthResult {
        ok: true,
        server_version: (!body.version.is_empty()).then_some(body.version),
        worker_model: (!body.worker_model.is_empty()).then_some(body.worker_model),
        capabilities: Some(caps),
        latency_ms: Some(latency),
    })
}

/// POST /auth/login —— 用口令换 JWT，令牌落钥匙串，前端只得到到期时间。
#[derive(Debug, Deserialize)]
struct LoginBody {
    token: String,
    expires_at: String,
}

pub struct LoginOutcome {
    pub expires_at: String,
}

pub async fn login(base_url: &str, connection_id: &str, password: &str) -> CmdResult<LoginOutcome> {
    let resp = client()?
        .post(format!("{base_url}/auth/login"))
        .json(&serde_json::json!({ "password": password }))
        .send()
        .await
        .map_err(ClientError::from)?;
    if !resp.status().is_success() {
        return Err(map_status(resp.status()));
    }
    let body: LoginBody = resp.json().await.map_err(ClientError::from)?;
    credentials::store_token(connection_id, &body.token)?;
    Ok(LoginOutcome { expires_at: body.expires_at })
}

/// 执行受控 API 操作，返回原始 JSON（前端按契约类型解析）。
pub async fn request(
    store: &ConnectionStore,
    connection_id: &str,
    op: ApiOperation,
) -> CmdResult<serde_json::Value> {
    let base_url = store.resolve_base_url(connection_id)?;
    let resolved = op.resolve();
    let url = format!("{base_url}{}", resolved.path);
    let c = client()?;
    let mut builder = match resolved.method {
        Method::Get => c.get(url),
        Method::Post => c.post(url),
    };
    if resolved.auth {
        let token = credentials::read_token(connection_id)?
            .ok_or_else(|| ClientError::new(ErrorKind::Unauthorized, "未登录", false))?;
        builder = builder.bearer_auth(token);
    }
    if let Some(body) = resolved.body {
        builder = builder.json(&body);
    }
    let resp = builder.send().await.map_err(ClientError::from)?;
    let status = resp.status();
    if !status.is_success() {
        return Err(map_status(status));
    }
    if status.as_u16() == 204 {
        return Ok(serde_json::Value::Null);
    }
    resp.json::<serde_json::Value>().await.map_err(ClientError::from)
}

/// HTTP 状态码 → ClientError.kind（方案 §8.1：Rust 归一化错误）。
fn map_status(status: reqwest::StatusCode) -> ClientError {
    let code = status.as_u16();
    let kind = match code {
        401 => ErrorKind::Unauthorized,
        403 => ErrorKind::Forbidden,
        404 => ErrorKind::NotFound,
        409 => ErrorKind::Conflict,
        400 | 422 => ErrorKind::Validation,
        500..=599 => ErrorKind::Backend,
        _ => ErrorKind::Backend,
    };
    let retryable = matches!(code, 502 | 503 | 504);
    ClientError::new(kind, format!("后端返回 {code}"), retryable).with_code(code.to_string())
}
