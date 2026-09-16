//! 连接命令：list / save / delete / test / activate。

use crate::backend_gateway::{self, HealthResult, ServerCapabilities};
use crate::connections::{ConnectionDraft, ConnectionProfile};
use crate::credentials;
use crate::error::{CmdResult, ErrorKind};
use crate::state::AppState;
use serde::{Deserialize, Serialize};
use tauri::State;

#[tauri::command]
pub fn connection_list(state: State<'_, AppState>) -> CmdResult<Vec<ConnectionProfile>> {
    Ok(state.connections.list())
}

#[tauri::command]
pub fn connection_save(state: State<'_, AppState>, input: ConnectionDraft) -> CmdResult<ConnectionProfile> {
    state.connections.save(input)
}

#[tauri::command]
pub fn connection_delete(state: State<'_, AppState>, id: String) -> CmdResult<()> {
    let _ = credentials::clear(&id);
    state.connections.delete(&id)
}

/// 测试连接：优先用已存 id 的 base_url，否则用草稿地址直探 /health。
#[tauri::command]
pub async fn connection_test(
    state: State<'_, AppState>,
    id: Option<String>,
    draft: Option<ConnectionDraft>,
) -> CmdResult<HealthResult> {
    let (base_url, ca) = match (id, draft) {
        (Some(id), _) => (state.connections.resolve_base_url(&id)?, state.connections.resolve_ca(&id)),
        (None, Some(d)) => {
            let url = crate::connections::normalize_base_url(&d.base_url)?;
            // HTTP 草稿忽略旧证书路径；仅 HTTPS + custom_ca 读取证书。
            let ca = match d.tls_policy {
                Some(crate::connections::TlsPolicy::CustomCa) if url.starts_with("https://") => d.ca_cert_path,
                _ => None,
            };
            (url, ca)
        }
        (None, None) => return Err(crate::error::ClientError::validation("需提供 id 或草稿地址")),
    };
    backend_gateway::health(&base_url, ca.as_deref()).await
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AuthSummary {
    pub authenticated: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expires_at: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub refresh_expires_at: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub user_label: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ConnectionSession {
    pub connection_id: String,
    pub status: String,
    pub auth: AuthSummary,
    pub health: HealthResult,
}

#[derive(Debug, Deserialize)]
struct MeBody {
    authenticated: bool,
    #[serde(default)]
    expires_at: Option<String>,
    #[serde(default)]
    refresh_expires_at: Option<String>,
}

/// 激活连接：探活、能力协商，并用 /auth/me 验证钥匙串中的令牌。
#[tauri::command]
pub async fn connection_activate(state: State<'_, AppState>, id: String) -> CmdResult<ConnectionSession> {
    let base_url = state.connections.resolve_base_url(&id)?;
    let ca = state.connections.resolve_ca(&id);
    let health = backend_gateway::health(&base_url, ca.as_deref()).await?;
    state
        .connections
        .mark_connected(&id, health.server_version.clone())?;

    let auth = if credentials::read_token(&id)?.is_some() {
        match backend_gateway::request(&state.connections, &id, backend_gateway::ApiOperation::Me).await {
            Ok(value) => {
                let body: MeBody = serde_json::from_value(value)?;
                AuthSummary {
                    authenticated: body.authenticated,
                    expires_at: body.expires_at,
                    refresh_expires_at: body.refresh_expires_at,
                    user_label: None,
                }
            }
            Err(error) => match error.kind {
                ErrorKind::Unauthorized => {
                    credentials::clear(&id)?;
                    AuthSummary {
                        authenticated: false,
                        expires_at: None,
                        refresh_expires_at: None,
                        user_label: None,
                    }
                }
                _ => return Err(error),
            },
        }
    } else {
        AuthSummary {
            authenticated: false,
            expires_at: None,
            refresh_expires_at: None,
            user_label: None,
        }
    };
    let status = if auth.authenticated { "online" } else { "unauthenticated" };

    Ok(ConnectionSession {
        connection_id: id,
        status: status.to_string(),
        auth,
        health: HealthResult {
            capabilities: health.capabilities.clone().or_else(|| Some(ServerCapabilities::default())),
            ..health
        },
    })
}
