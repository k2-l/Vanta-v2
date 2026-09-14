//! 系统命令：诊断导出、更新检查、产物导出。G0 提供最小实现/占位。

use crate::error::{ClientError, CmdResult, ErrorKind};
use serde::Serialize;

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateInfo {
    pub available: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub version: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub notes: Option<String>,
}

/// G0：更新服务未接入（方案 §14.3 要求签名更新，G4 落地）。
#[tauri::command]
pub async fn app_check_update() -> CmdResult<UpdateInfo> {
    Ok(UpdateInfo { available: false, version: None, notes: None })
}

fn not_yet(gate: &str) -> ClientError {
    ClientError::new(ErrorKind::Desktop, format!("将在 {gate} 阶段接入"), false)
}

#[tauri::command]
pub async fn artifact_export(_connection_id: String, _artifact_id: String) -> CmdResult<serde_json::Value> {
    Err(not_yet("G3"))
}

#[tauri::command]
pub async fn diagnostics_export() -> CmdResult<serde_json::Value> {
    Err(not_yet("G4"))
}
