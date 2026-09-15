//! 后端网关（方案 §8）。
//!
//! 职责：按 connection_id 解析地址（前端不传任意 URL）、注入凭据、设定超时、
//! 归一化错误。流式桥接由 `commands::stream` 处理。

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
    #[serde(rename = "runs.list")]
    RunsList {
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
        #[serde(rename = "sessionId", alias = "session_id")]
        session_id: String,
        #[serde(default)]
        limit: Option<u32>,
    },
    #[serde(rename = "sessions.phases")]
    SessionsPhases {
        #[serde(rename = "sessionId", alias = "session_id")]
        session_id: String,
    },
    #[serde(rename = "sessions.events")]
    SessionsEvents {
        #[serde(rename = "sessionId", alias = "session_id")]
        session_id: String,
        #[serde(default, rename = "afterSeq", alias = "after_seq")]
        after_seq: Option<u64>,
        #[serde(default)]
        limit: Option<u32>,
    },
    #[serde(rename = "approvals.list")]
    ApprovalsList,
    #[serde(rename = "approvals.decide")]
    ApprovalsDecide {
        #[serde(rename = "callId", alias = "call_id")]
        call_id: String,
        approved: bool,
    },
    #[serde(rename = "approvals.history")]
    ApprovalsHistory {
        #[serde(default)]
        limit: Option<u32>,
    },
    #[serde(rename = "artifacts.list")]
    ArtifactsList {
        #[serde(default)]
        kind: Option<String>,
    },
    #[serde(rename = "budget.get")]
    BudgetGet {
        #[serde(rename = "sessionId", alias = "session_id")]
        session_id: String,
    },
    #[serde(rename = "capabilities.agents")]
    CapabilitiesAgents,
    #[serde(rename = "capabilities.skills")]
    CapabilitiesSkills,
    #[serde(rename = "capabilities.mcp")]
    CapabilitiesMcp,
    #[serde(rename = "capabilities.knowledge")]
    CapabilitiesKnowledge,
    #[serde(rename = "capabilities.containers")]
    CapabilitiesContainers,
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
            ApiOperation::RunsList { limit } => Resolved {
                method: Method::Get,
                path: format!("/runs?limit={}", limit.unwrap_or(60)),
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
            ApiOperation::SessionsPhases { session_id } => Resolved {
                method: Method::Get,
                path: format!("/sessions/{session_id}/phases"),
                body: None,
                auth: true,
            },
            ApiOperation::SessionsEvents { session_id, after_seq, limit } => Resolved {
                method: Method::Get,
                path: format!(
                    "/sessions/{session_id}/events?after_seq={}&limit={}",
                    after_seq.unwrap_or(0),
                    limit.unwrap_or(1000)
                ),
                body: None,
                auth: true,
            },
            ApiOperation::ApprovalsList => Resolved {
                method: Method::Get,
                path: "/chat/approvals".into(),
                body: None,
                auth: true,
            },
            ApiOperation::ApprovalsDecide { call_id, approved } => Resolved {
                method: Method::Post,
                path: format!("/chat/approvals/{call_id}"),
                body: Some(serde_json::json!({ "approved": approved })),
                auth: true,
            },
            ApiOperation::ApprovalsHistory { limit } => Resolved {
                method: Method::Get,
                path: format!("/chat/approvals/history?limit={}", limit.unwrap_or(100)),
                body: None,
                auth: true,
            },
            ApiOperation::ArtifactsList { kind } => Resolved {
                method: Method::Get,
                path: match kind {
                    Some(k) => format!("/v1/artifacts?kind={k}"),
                    None => "/v1/artifacts".into(),
                },
                body: None,
                auth: true,
            },
            ApiOperation::BudgetGet { session_id } => Resolved {
                method: Method::Get,
                path: format!("/budget/{session_id}"),
                body: None,
                auth: true,
            },
            ApiOperation::CapabilitiesAgents => Resolved {
                method: Method::Get,
                path: "/v1/agents".into(),
                body: None,
                auth: true,
            },
            ApiOperation::CapabilitiesSkills => Resolved {
                method: Method::Get,
                path: "/v1/skills".into(),
                body: None,
                auth: true,
            },
            ApiOperation::CapabilitiesMcp => Resolved {
                method: Method::Get,
                path: "/v1/mcp/servers".into(),
                body: None,
                auth: true,
            },
            ApiOperation::CapabilitiesKnowledge => Resolved {
                method: Method::Get,
                path: "/v1/knowledge".into(),
                body: None,
                auth: true,
            },
            ApiOperation::CapabilitiesContainers => Resolved {
                method: Method::Get,
                path: "/v1/containers".into(),
                body: None,
                auth: true,
            },
        }
    }
}

/// 按连接的 TLS 策略构建 reqwest client。
///
/// custom_ca 时把指定的 PEM 证书**追加**到信任根（系统根之外增量，不降低校验强度），
/// 让桌面端无需把自签证书装进操作系统信任库即可校验通过。
/// `overall_timeout=None` 表示不设整体请求超时（用于可能长时间的对话流）。
pub fn build_client(ca_cert_path: Option<&str>, overall_timeout: Option<Duration>) -> CmdResult<reqwest::Client> {
    let mut builder = reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(6))
        // 瘦客户端连的是用户自配的后端（内网/回环），绝不经环境/系统代理，
        // 否则 HTTP(S)_PROXY 会把内网地址塞去走代理导致 connect 失败。
        .no_proxy()
        .user_agent("Vanta-Desktop/0.0.0");
    if let Some(timeout) = overall_timeout {
        builder = builder.timeout(timeout);
    }
    if let Some(path) = ca_cert_path {
        let pem = std::fs::read(path).map_err(|e| {
            ClientError::new(ErrorKind::Validation, format!("读取 CA 证书失败（{path}）：{e}"), false)
        })?;
        let certs = reqwest::Certificate::from_pem_bundle(&pem).map_err(|e| {
            ClientError::new(ErrorKind::Validation, format!("CA 证书解析失败：{e}"), false)
        })?;
        for cert in certs {
            builder = builder.add_root_certificate(cert);
        }
    }
    builder.build().map_err(ClientError::from)
}

/// /health 响应；旧后端未提供 capabilities 时缺省为全 false。
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
    #[serde(default, alias = "api_version")]
    pub api_version: Option<String>,
    #[serde(default, alias = "run_snapshot")]
    pub run_snapshot: bool,
    #[serde(default, alias = "run_history")]
    pub run_history: bool,
    #[serde(default, alias = "event_replay")]
    pub event_replay: bool,
    #[serde(default, alias = "run_cancel")]
    pub run_cancel: bool,
    #[serde(default, alias = "artifact_export")]
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
/// `ca_cert_path` 供 custom_ca 连接在探活/测试时也走自定义信任根。
pub async fn health(base_url: &str, ca_cert_path: Option<&str>) -> CmdResult<HealthResult> {
    let start = std::time::Instant::now();
    let resp = build_client(ca_cert_path, Some(Duration::from_secs(30)))?
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

pub async fn login(
    base_url: &str,
    connection_id: &str,
    password: &str,
    ca_cert_path: Option<&str>,
) -> CmdResult<LoginOutcome> {
    let resp = build_client(ca_cert_path, Some(Duration::from_secs(30)))?
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
    let ca = store.resolve_ca(connection_id);
    let resolved = op.resolve();
    let url = format!("{base_url}{}", resolved.path);
    let c = build_client(ca.as_deref(), Some(Duration::from_secs(30)))?;
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
pub(crate) fn map_status(status: reqwest::StatusCode) -> ClientError {
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

#[cfg(test)]
mod tests {
    use super::ApiOperation;
    use serde_json::{json, Value};

    #[test]
    fn api_operations_accept_frontend_camel_case_ids() {
        let cases: [(Value, &str); 6] = [
            (
                json!({ "op": "sessions.messages", "sessionId": "session-1", "limit": 20 }),
                "/sessions/session-1/messages?limit=20",
            ),
            (
                json!({ "op": "sessions.phases", "sessionId": "session-1" }),
                "/sessions/session-1/phases",
            ),
            (
                json!({ "op": "sessions.events", "sessionId": "session-1", "afterSeq": 7, "limit": 25 }),
                "/sessions/session-1/events?after_seq=7&limit=25",
            ),
            (
                json!({ "op": "budget.get", "sessionId": "session-1" }),
                "/budget/session-1",
            ),
            (
                json!({ "op": "approvals.decide", "callId": "call-1", "approved": true }),
                "/chat/approvals/call-1",
            ),
            (
                json!({ "op": "approvals.history", "limit": 50 }),
                "/chat/approvals/history?limit=50",
            ),
        ];

        for (value, expected_path) in cases {
            let operation: ApiOperation = serde_json::from_value(value).unwrap();
            assert_eq!(operation.resolve().path, expected_path);
        }
    }

    #[test]
    fn api_operations_keep_snake_case_id_aliases() {
        let operation: ApiOperation = serde_json::from_value(json!({
            "op": "sessions.phases",
            "session_id": "session-1"
        }))
        .unwrap();
        assert_eq!(operation.resolve().path, "/sessions/session-1/phases");

        let operation: ApiOperation = serde_json::from_value(json!({
            "op": "approvals.decide",
            "call_id": "call-1",
            "approved": false
        }))
        .unwrap();
        assert_eq!(operation.resolve().body, Some(json!({ "approved": false })));
    }
}
