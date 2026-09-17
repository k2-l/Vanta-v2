//! 后端网关（方案 §8）。
//!
//! 职责：按 connection_id 解析地址（前端不传任意 URL）、注入凭据、设定超时、
//! 归一化错误。流式桥接由 `commands::stream` 处理。

use crate::connections::ConnectionStore;
use crate::credentials;
use crate::error::{ClientError, CmdResult, ErrorKind};
use serde::{Deserialize, Serialize};
use std::sync::OnceLock;
use std::time::Duration;

/// 刷新令牌是一次性轮换的；串行化刷新，避免并发 401 让两个请求复用同一旧令牌。
static REFRESH_LOCK: OnceLock<tokio::sync::Mutex<()>> = OnceLock::new();

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
        #[serde(rename = "sessionId")]
        session_id: String,
        #[serde(default)]
        limit: Option<u32>,
    },
    #[serde(rename = "sessions.compress.preview")]
    SessionsCompressPreview {
        #[serde(rename = "sessionId")]
        session_id: String,
    },
    #[serde(rename = "sessions.compress.commit")]
    SessionsCompressCommit {
        #[serde(rename = "sessionId")]
        session_id: String,
        summary: String,
        upto: String,
    },
    #[serde(rename = "sessions.phases")]
    SessionsPhases {
        #[serde(rename = "sessionId")]
        session_id: String,
    },
    #[serde(rename = "sessions.events")]
    SessionsEvents {
        #[serde(rename = "sessionId")]
        session_id: String,
        #[serde(default, rename = "afterSeq")]
        after_seq: Option<u64>,
        #[serde(default)]
        limit: Option<u32>,
    },
    #[serde(rename = "sessions.patch")]
    SessionsPatch {
        #[serde(rename = "sessionId")]
        session_id: String,
        title: String,
    },
    #[serde(rename = "sessions.delete")]
    SessionsDelete {
        #[serde(rename = "sessionId")]
        session_id: String,
    },
    #[serde(rename = "approvals.list")]
    ApprovalsList,
    #[serde(rename = "approvals.decide")]
    ApprovalsDecide {
        #[serde(rename = "callId")]
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
        #[serde(default, rename = "sessionId")]
        session_id: Option<String>,
    },
    #[serde(rename = "artifacts.get")]
    ArtifactsGet {
        #[serde(rename = "artifactId")]
        artifact_id: String,
    },
    #[serde(rename = "artifacts.delete")]
    ArtifactsDelete {
        #[serde(rename = "artifactId")]
        artifact_id: String,
    },
    #[serde(rename = "budget.get")]
    BudgetGet {
        #[serde(rename = "sessionId")]
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
    #[serde(rename = "containers.create")]
    ContainersCreate { input: serde_json::Value },
    #[serde(rename = "containers.start")]
    ContainersStart {
        #[serde(rename = "containerId")]
        container_id: String,
    },
    #[serde(rename = "containers.stop")]
    ContainersStop {
        #[serde(rename = "containerId")]
        container_id: String,
    },
    #[serde(rename = "containers.delete")]
    ContainersDelete {
        #[serde(rename = "containerId")]
        container_id: String,
    },
    #[serde(rename = "containers.profile.get")]
    ContainersProfileGet {
        #[serde(rename = "containerId")]
        container_id: String,
    },
    #[serde(rename = "containers.profile.put")]
    ContainersProfilePut {
        #[serde(rename = "containerId")]
        container_id: String,
        input: serde_json::Value,
    },
    #[serde(rename = "containers.profile.delete")]
    ContainersProfileDelete {
        #[serde(rename = "containerId")]
        container_id: String,
    },
    #[serde(rename = "containers.readiness")]
    ContainersReadiness {
        #[serde(rename = "containerId")]
        container_id: String,
    },
}

#[derive(Clone, Copy)]
enum Method {
    Get,
    Post,
    Put,
    Patch,
    Delete,
}

struct Resolved {
    method: Method,
    path: String,
    body: Option<serde_json::Value>,
    /// 是否需要鉴权（health 为公开路由）。
    auth: bool,
}

impl ApiOperation {
    fn timeout(&self) -> Duration {
        // 压缩预览会调用摘要模型，不能沿用普通 CRUD 的 30 秒总超时。
        if matches!(self, ApiOperation::SessionsCompressPreview { .. }) {
            Duration::from_secs(120)
        } else if matches!(self, ApiOperation::ContainersCreate { .. }) {
            Duration::from_secs(150)
        } else if matches!(
            self,
            ApiOperation::ContainersStart { .. }
                | ApiOperation::ContainersStop { .. }
                | ApiOperation::ContainersDelete { .. }
                | ApiOperation::ContainersReadiness { .. }
                | ApiOperation::ContainersProfilePut { .. }
        ) {
            Duration::from_secs(45)
        } else {
            Duration::from_secs(30)
        }
    }

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
            ApiOperation::SessionsCompressPreview { session_id } => Resolved {
                method: Method::Post,
                path: format!("/sessions/{session_id}/compress/preview"),
                body: None,
                auth: true,
            },
            ApiOperation::SessionsCompressCommit { session_id, summary, upto } => Resolved {
                method: Method::Post,
                path: format!("/sessions/{session_id}/compress/commit"),
                body: Some(serde_json::json!({ "summary": summary, "upto": upto })),
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
            ApiOperation::SessionsPatch { session_id, title } => Resolved {
                method: Method::Patch,
                path: format!("/sessions/{session_id}"),
                body: Some(serde_json::json!({ "title": title })),
                auth: true,
            },
            ApiOperation::SessionsDelete { session_id } => Resolved {
                method: Method::Delete,
                path: format!("/sessions/{session_id}"),
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
            ApiOperation::ArtifactsList { kind, session_id } => Resolved {
                method: Method::Get,
                path: {
                    let mut query = Vec::new();
                    if let Some(k) = kind {
                        query.push(format!("kind={}", encode_query_component(k)));
                    }
                    if let Some(id) = session_id {
                        query.push(format!("session_id={}", encode_query_component(id)));
                    }
                    if query.is_empty() {
                        "/v1/artifacts".into()
                    } else {
                        format!("/v1/artifacts?{}", query.join("&"))
                    }
                },
                body: None,
                auth: true,
            },
            ApiOperation::ArtifactsGet { artifact_id } => Resolved {
                method: Method::Get,
                path: format!("/v1/artifacts/{}", encode_query_component(artifact_id)),
                body: None,
                auth: true,
            },
            ApiOperation::ArtifactsDelete { artifact_id } => Resolved {
                method: Method::Delete,
                path: format!("/v1/artifacts/{}", encode_query_component(artifact_id)),
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
            ApiOperation::ContainersCreate { input } => Resolved {
                method: Method::Post,
                path: "/v1/containers".into(),
                body: Some(input.clone()),
                auth: true,
            },
            ApiOperation::ContainersStart { container_id } => Resolved {
                method: Method::Patch,
                path: format!(
                    "/v1/containers/{}/start",
                    encode_query_component(container_id)
                ),
                body: None,
                auth: true,
            },
            ApiOperation::ContainersStop { container_id } => Resolved {
                method: Method::Patch,
                path: format!(
                    "/v1/containers/{}/stop",
                    encode_query_component(container_id)
                ),
                body: None,
                auth: true,
            },
            ApiOperation::ContainersDelete { container_id } => Resolved {
                method: Method::Delete,
                path: format!("/v1/containers/{}", encode_query_component(container_id)),
                body: None,
                auth: true,
            },
            ApiOperation::ContainersProfileGet { container_id } => Resolved {
                method: Method::Get,
                path: format!(
                    "/v1/containers/{}/profile",
                    encode_query_component(container_id)
                ),
                body: None,
                auth: true,
            },
            ApiOperation::ContainersProfilePut {
                container_id,
                input,
            } => Resolved {
                method: Method::Put,
                path: format!(
                    "/v1/containers/{}/profile",
                    encode_query_component(container_id)
                ),
                body: Some(input.clone()),
                auth: true,
            },
            ApiOperation::ContainersProfileDelete { container_id } => Resolved {
                method: Method::Delete,
                path: format!(
                    "/v1/containers/{}/profile",
                    encode_query_component(container_id)
                ),
                body: None,
                auth: true,
            },
            ApiOperation::ContainersReadiness { container_id } => Resolved {
                method: Method::Get,
                path: format!(
                    "/v1/containers/{}/readiness",
                    encode_query_component(container_id)
                ),
                body: None,
                auth: true,
            },
        }
    }
}

fn encode_query_component(value: &str) -> String {
    let mut encoded = String::with_capacity(value.len());
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b'~') {
            encoded.push(byte as char);
        } else {
            encoded.push_str(&format!("%{byte:02X}"));
        }
    }
    encoded
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

fn validate_api_version(version: Option<&str>) -> CmdResult<()> {
    match version {
        Some("1") => Ok(()),
        Some(other) => Err(ClientError::new(
            ErrorKind::Protocol,
            format!("后端 API 版本不受支持：{other}（客户端需要 1）"),
            false,
        )),
        None => Err(ClientError::new(
            ErrorKind::Protocol,
            "后端未声明 API 版本，不能安全联调",
            false,
        )),
    }
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
    validate_api_version(caps.api_version.as_deref())?;
    Ok(HealthResult {
        ok: true,
        server_version: (!body.version.is_empty()).then_some(body.version),
        worker_model: (!body.worker_model.is_empty()).then_some(body.worker_model),
        capabilities: Some(caps),
        latency_ms: Some(latency),
    })
}

/// 登录/刷新响应；两个令牌都只进入系统钥匙串，WebView 只得到到期时间。
#[derive(Debug, Deserialize)]
struct LoginBody {
    token: String,
    refresh_token: String,
    expires_at: String,
    refresh_expires_at: String,
}

pub struct LoginOutcome {
    pub expires_at: String,
    pub refresh_expires_at: String,
}

fn store_login_body(connection_id: &str, body: LoginBody) -> CmdResult<LoginOutcome> {
    credentials::store_token_pair(connection_id, &body.token, &body.refresh_token)?;
    Ok(LoginOutcome {
        expires_at: body.expires_at,
        refresh_expires_at: body.refresh_expires_at,
    })
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
    store_login_body(connection_id, body)
}

/// 用钥匙串中的一次性刷新令牌轮换令牌对。
pub async fn refresh(
    base_url: &str,
    connection_id: &str,
    ca_cert_path: Option<&str>,
) -> CmdResult<LoginOutcome> {
    let _guard = REFRESH_LOCK.get_or_init(|| tokio::sync::Mutex::new(())).lock().await;
    let refresh_token = credentials::read_refresh_token(connection_id)?
        .ok_or_else(|| ClientError::new(ErrorKind::Unauthorized, "登录已过期，请重新登录", false))?;
    let resp = build_client(ca_cert_path, Some(Duration::from_secs(30)))?
        .post(format!("{base_url}/auth/refresh"))
        .json(&serde_json::json!({ "refresh_token": refresh_token }))
        .send()
        .await
        .map_err(ClientError::from)?;
    if !resp.status().is_success() {
        if resp.status() == reqwest::StatusCode::UNAUTHORIZED {
            let _ = credentials::clear(connection_id);
        }
        return Err(map_status(resp.status()));
    }
    let body: LoginBody = resp.json().await.map_err(ClientError::from)?;
    store_login_body(connection_id, body)
}

/// 撤销服务端登录会话。调用方无论结果如何都应清理本机凭据。
pub async fn revoke_session(
    base_url: &str,
    connection_id: &str,
    ca_cert_path: Option<&str>,
) -> CmdResult<()> {
    let token = credentials::read_token(connection_id)?
        .ok_or_else(|| ClientError::new(ErrorKind::Unauthorized, "未登录", false))?;
    let resp = build_client(ca_cert_path, Some(Duration::from_secs(30)))?
        .post(format!("{base_url}/auth/logout"))
        .bearer_auth(token)
        .send()
        .await
        .map_err(ClientError::from)?;
    if resp.status().is_success() || resp.status() == reqwest::StatusCode::UNAUTHORIZED {
        Ok(())
    } else {
        Err(map_status(resp.status()))
    }
}

/// 执行受控 API 操作，返回原始 JSON（前端按契约类型解析）。
pub async fn request(
    store: &ConnectionStore,
    connection_id: &str,
    op: ApiOperation,
) -> CmdResult<serde_json::Value> {
    let base_url = store.resolve_base_url(connection_id)?;
    let ca = store.resolve_ca(connection_id);
    let timeout = op.timeout();
    let resolved = op.resolve();
    let url = format!("{base_url}{}", resolved.path);
    let c = build_client(ca.as_deref(), Some(timeout))?;
    let mut token = if resolved.auth {
        Some(
            credentials::read_token(connection_id)?
                .ok_or_else(|| ClientError::new(ErrorKind::Unauthorized, "未登录", false))?,
        )
    } else {
        None
    };
    let mut refreshed = false;
    let resp = loop {
        let mut builder = match resolved.method {
            Method::Get => c.get(&url),
            Method::Post => c.post(&url),
            Method::Put => c.put(&url),
            Method::Patch => c.patch(&url),
            Method::Delete => c.delete(&url),
        };
        if let Some(access) = token.as_deref() {
            builder = builder.bearer_auth(access);
        }
        if let Some(body) = resolved.body.as_ref() {
            builder = builder.json(body);
        }
        let response = builder.send().await.map_err(ClientError::from)?;
        if response.status() != reqwest::StatusCode::UNAUTHORIZED || !resolved.auth || refreshed {
            break response;
        }
        refresh(&base_url, connection_id, ca.as_deref()).await?;
        token = credentials::read_token(connection_id)?;
        refreshed = true;
    };
    let status = resp.status();
    if !status.is_success() {
        let request_id = resp
            .headers()
            .get("x-request-id")
            .and_then(|value| value.to_str().ok())
            .map(str::to_owned);
        let body = resp.json::<serde_json::Value>().await.ok();
        let mut error = map_status(status);
        if let Some(message) = body.as_ref().and_then(backend_error_message) {
            error.message = message;
        }
        error.request_id = request_id;
        return Err(error);
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

/// Extract FastAPI's safe validation/detail message without reflecting request input
/// (which may contain container environment secrets) back into the WebView.
fn backend_error_message(body: &serde_json::Value) -> Option<String> {
    let detail = body.get("detail")?;
    let message = match detail {
        serde_json::Value::String(value) => value.trim().to_owned(),
        serde_json::Value::Array(items) => items
            .iter()
            .filter_map(|item| {
                let message = item.get("msg")?.as_str()?.trim();
                if message.is_empty() {
                    return None;
                }
                let location = item
                    .get("loc")
                    .and_then(serde_json::Value::as_array)
                    .map(|parts| {
                        parts
                            .iter()
                            .filter_map(serde_json::Value::as_str)
                            .collect::<Vec<_>>()
                            .join(".")
                    })
                    .filter(|value| !value.is_empty());
                Some(match location {
                    Some(location) => format!("{location}: {message}"),
                    None => message.to_owned(),
                })
            })
            .take(3)
            .collect::<Vec<_>>()
            .join("；"),
        _ => String::new(),
    };
    if message.is_empty() {
        None
    } else {
        Some(message.chars().take(500).collect())
    }
}

#[cfg(test)]
mod tests {
    use super::{backend_error_message, validate_api_version, ApiOperation};
    use serde_json::{json, Value};

    #[test]
    fn api_operations_accept_frontend_camel_case_ids() {
        let cases: [(Value, &str); 13] = [
            (
                json!({ "op": "sessions.messages", "sessionId": "session-1", "limit": 20 }),
                "/sessions/session-1/messages?limit=20",
            ),
            (
                json!({ "op": "sessions.phases", "sessionId": "session-1" }),
                "/sessions/session-1/phases",
            ),
            (
                json!({ "op": "sessions.compress.preview", "sessionId": "session-1" }),
                "/sessions/session-1/compress/preview",
            ),
            (
                json!({ "op": "sessions.compress.commit", "sessionId": "session-1", "summary": "摘要", "upto": "2026-09-16T12:00:00Z" }),
                "/sessions/session-1/compress/commit",
            ),
            (
                json!({ "op": "sessions.patch", "sessionId": "session-1", "title": "新标题" }),
                "/sessions/session-1",
            ),
            (
                json!({ "op": "sessions.delete", "sessionId": "session-1" }),
                "/sessions/session-1",
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
            (
                json!({ "op": "artifacts.list", "kind": "scan result", "sessionId": "session/1" }),
                "/v1/artifacts?kind=scan%20result&session_id=session%2F1",
            ),
            (
                json!({ "op": "artifacts.get", "artifactId": "artifact/1" }),
                "/v1/artifacts/artifact%2F1",
            ),
            (
                json!({ "op": "artifacts.delete", "artifactId": "artifact/1" }),
                "/v1/artifacts/artifact%2F1",
            ),
        ];

        for (value, expected_path) in cases {
            let operation: ApiOperation = serde_json::from_value(value).unwrap();
            assert_eq!(operation.resolve().path, expected_path);
        }
    }

    #[test]
    fn sessions_patch_sends_title_body_and_delete_sends_none() {
        let patch: ApiOperation =
            serde_json::from_value(json!({ "op": "sessions.patch", "sessionId": "s1", "title": "改后的标题" }))
                .unwrap();
        let resolved = patch.resolve();
        assert!(matches!(resolved.method, super::Method::Patch));
        assert_eq!(resolved.body, Some(json!({ "title": "改后的标题" })));
        assert!(resolved.auth);

        let delete: ApiOperation =
            serde_json::from_value(json!({ "op": "sessions.delete", "sessionId": "s1" })).unwrap();
        let resolved = delete.resolve();
        assert!(matches!(resolved.method, super::Method::Delete));
        assert_eq!(resolved.body, None);
    }

    #[test]
    fn container_operations_are_allowlisted_with_fixed_paths() {
        let create_body = json!({
            "name": "java-runtime",
            "image": "example/java:17",
            "ports": [],
            "env_vars": [],
            "command": ["sleep", "infinity"],
            "network_mode": "none",
            "working_dir": "/workspace"
        });
        let create: ApiOperation = serde_json::from_value(json!({
            "op": "containers.create",
            "input": create_body.clone()
        }))
        .unwrap();
        let resolved = create.resolve();
        assert!(matches!(resolved.method, super::Method::Post));
        assert_eq!(resolved.path, "/v1/containers");
        assert_eq!(resolved.body, Some(create_body));

        let profile_body = json!({
            "capabilities": ["jdk17"],
            "purpose": "java-audit",
            "workspace_mode": "read-only",
            "network_policy": "none",
            "default_workdir": "/workspace",
            "agent_allowlist": ["java-auditor"],
            "max_concurrency": 1,
            "agent_ready": true
        });
        let profile: ApiOperation = serde_json::from_value(json!({
            "op": "containers.profile.put",
            "containerId": "record/1",
            "input": profile_body.clone()
        }))
        .unwrap();
        let resolved = profile.resolve();
        assert!(matches!(resolved.method, super::Method::Put));
        assert_eq!(resolved.path, "/v1/containers/record%2F1/profile");
        assert_eq!(resolved.body, Some(profile_body));

        let readiness: ApiOperation = serde_json::from_value(json!({
            "op": "containers.readiness",
            "containerId": "record/1"
        }))
        .unwrap();
        assert_eq!(
            readiness.resolve().path,
            "/v1/containers/record%2F1/readiness"
        );
    }

    #[test]
    fn backend_errors_expose_detail_without_reflecting_request_input() {
        assert_eq!(
            backend_error_message(&json!({ "detail": "Profile 声明禁网，但容器实际网络模式不是 none" })),
            Some("Profile 声明禁网，但容器实际网络模式不是 none".into())
        );
        assert_eq!(
            backend_error_message(&json!({
                "detail": [{
                    "loc": ["body", "max_concurrency"],
                    "msg": "Input should be greater than or equal to 1",
                    "input": "sensitive-value"
                }]
            })),
            Some("body.max_concurrency: Input should be greater than or equal to 1".into())
        );
    }

    #[test]
    fn health_requires_the_current_backend_api_contract() {
        assert!(validate_api_version(Some("1")).is_ok());
        assert!(validate_api_version(Some("2")).is_err());
        assert!(validate_api_version(None).is_err());
    }

}
