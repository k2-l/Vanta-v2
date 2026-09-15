//! 系统命令：诊断导出、更新检查、产物导出。

use crate::diagnostics;
use crate::error::{ClientError, CmdResult, ErrorKind};
use crate::state::AppState;
use serde::Serialize;
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{Manager, State};

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateInfo {
    pub available: bool,
    /// 是否已接入签名更新渠道。false 时前端应如实说明"自动更新尚未接入"，
    /// 而非展示"已是最新版本"（方案 §14.3；真实签名更新为后续增量）。
    pub configured: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub version: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub notes: Option<String>,
}

/// 更新服务尚未接入：如实返回 configured=false，前端据此给出诚实文案。
#[tauri::command]
pub async fn app_check_update() -> CmdResult<UpdateInfo> {
    Ok(UpdateInfo { available: false, configured: false, version: None, notes: None })
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExportResult {
    pub path: String,
    pub bytes: u64,
}

#[tauri::command]
pub async fn artifact_export(_connection_id: String, _artifact_id: String) -> CmdResult<serde_json::Value> {
    Err(ClientError::new(ErrorKind::Desktop, "产物导出尚未接入", false))
}

/// 导出脱敏诊断包（方案 §14.2 / §17）。
///
/// 路径由 Rust Core 选定（app_log_dir，不接受 WebView 传入路径）。不读取钥匙串令牌；
/// 连接名称和 URL 是用户输入，可能包含敏感信息，有限的标记脱敏不保证全部清除。
#[tauri::command]
pub async fn diagnostics_export(app: tauri::AppHandle, state: State<'_, AppState>) -> CmdResult<ExportResult> {
    let now_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);

    let connections: Vec<serde_json::Value> = state
        .connections
        .list()
        .into_iter()
        .map(|c| {
            serde_json::json!({
                "id": c.id,
                "label": c.label,
                "baseUrl": c.base_url,
                "tlsPolicy": c.tls_policy,
                "lastConnectedAt": c.last_connected_at,
                "lastKnownVersion": c.last_known_version,
            })
        })
        .collect();

    let snapshot = serde_json::json!({
        "appVersion": env!("CARGO_PKG_VERSION"),
        "platform": std::env::consts::OS,
        "arch": std::env::consts::ARCH,
        "generatedAtMs": now_ms,
        "note": "未读取钥匙串令牌；连接名称与地址可能含用户输入的敏感信息，请分享前核对。",
        "connections": connections,
    });

    let pretty = serde_json::to_string_pretty(&snapshot)?;
    let body = diagnostics::redact(&pretty);

    let dir = app
        .path()
        .app_log_dir()
        .map_err(|e| ClientError::new(ErrorKind::Desktop, format!("无法解析诊断目录：{e}"), false))?;
    std::fs::create_dir_all(&dir)?;
    let path = dir.join(format!("vanta-diagnostics-{now_ms}.json"));
    std::fs::write(&path, body.as_bytes())?;

    Ok(ExportResult {
        path: path.to_string_lossy().into_owned(),
        bytes: body.len() as u64,
    })
}
