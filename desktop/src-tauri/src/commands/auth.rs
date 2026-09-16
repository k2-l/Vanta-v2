//! 认证命令：login / logout。口令只作一次性入参，令牌落钥匙串。

use crate::backend_gateway;
use super::connection::AuthSummary;
use crate::credentials;
use crate::error::CmdResult;
use crate::state::AppState;
use tauri::State;

#[tauri::command]
pub async fn auth_login(
    state: State<'_, AppState>,
    connection_id: String,
    password: String,
) -> CmdResult<AuthSummary> {
    let base_url = state.connections.resolve_base_url(&connection_id)?;
    let ca = state.connections.resolve_ca(&connection_id);
    let outcome = backend_gateway::login(&base_url, &connection_id, &password, ca.as_deref()).await?;
    // password 在此作用域结束即释放；从不写日志、从不回传前端。
    Ok(AuthSummary {
        authenticated: true,
        expires_at: Some(outcome.expires_at),
        refresh_expires_at: Some(outcome.refresh_expires_at),
        user_label: None,
    })
}

#[tauri::command]
pub async fn auth_refresh(
    state: State<'_, AppState>,
    connection_id: String,
) -> CmdResult<AuthSummary> {
    let base_url = state.connections.resolve_base_url(&connection_id)?;
    let ca = state.connections.resolve_ca(&connection_id);
    let outcome = backend_gateway::refresh(&base_url, &connection_id, ca.as_deref()).await?;
    Ok(AuthSummary {
        authenticated: true,
        expires_at: Some(outcome.expires_at),
        refresh_expires_at: Some(outcome.refresh_expires_at),
        user_label: None,
    })
}

#[tauri::command]
pub async fn auth_logout(
    state: State<'_, AppState>,
    connection_id: String,
) -> CmdResult<()> {
    let base_url = state.connections.resolve_base_url(&connection_id)?;
    let ca = state.connections.resolve_ca(&connection_id);
    let revoke = backend_gateway::revoke_session(&base_url, &connection_id, ca.as_deref()).await;
    let cleared = credentials::clear(&connection_id);
    revoke.and(cleared)
}
