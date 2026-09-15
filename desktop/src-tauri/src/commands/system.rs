//! 系统命令：诊断导出、更新检查、产物导出。

use crate::backend_gateway::{self, ApiOperation};
use crate::diagnostics;
use crate::error::{ClientError, CmdResult, ErrorKind};
use crate::state::AppState;
use serde::{Deserialize, Serialize};
use std::io::Write;
use std::path::{Path, PathBuf};
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

#[derive(Debug, Deserialize)]
struct ExportableArtifact {
    id: String,
    title: String,
    kind: String,
    #[serde(default)]
    media_type: String,
    #[serde(default)]
    sensitivity: String,
    #[serde(default)]
    content: String,
}

/// 受控产物导出：WebView 只传连接与产物 id，不能指定路径或正文。
/// Rust Core 从后端重新读取权威内容，拒绝 secret，并写入系统下载目录下的 Vanta Exports。
#[tauri::command]
pub async fn artifact_export(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
    connection_id: String,
    artifact_id: String,
) -> CmdResult<ExportResult> {
    let requested_artifact_id = artifact_id.clone();
    let raw = backend_gateway::request(
        &state.connections,
        &connection_id,
        ApiOperation::ArtifactsGet { artifact_id },
    )
    .await?;
    let artifact: ExportableArtifact = serde_json::from_value(raw)?;
    if artifact.id != requested_artifact_id {
        return Err(ClientError::new(
            ErrorKind::Protocol,
            "后端返回的产物标识与请求不一致",
            false,
        ));
    }
    if artifact.sensitivity == "secret" {
        return Err(ClientError::new(
            ErrorKind::Forbidden,
            "机密产物不允许导出正文",
            false,
        ));
    }
    if artifact.content.is_empty() {
        return Err(ClientError::new(
            ErrorKind::Validation,
            "产物没有可导出的正文",
            false,
        ));
    }
    const MAX_EXPORT_BYTES: usize = 64 * 1024 * 1024;
    if artifact.content.len() > MAX_EXPORT_BYTES {
        return Err(ClientError::new(
            ErrorKind::Validation,
            "产物超过 64 MiB 导出上限",
            false,
        ));
    }

    let dir = app
        .path()
        .download_dir()
        .map_err(|e| ClientError::desktop(format!("无法解析下载目录：{e}")))?
        .join("Vanta Exports");
    std::fs::create_dir_all(&dir)?;
    let nonce = uuid::Uuid::new_v4().simple().to_string();
    let path = export_path(&dir, &artifact, &nonce[..8]);
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&path)?;
    file.write_all(artifact.content.as_bytes())?;

    Ok(ExportResult {
        path: path.to_string_lossy().into_owned(),
        bytes: artifact.content.len() as u64,
    })
}

fn export_path(dir: &Path, artifact: &ExportableArtifact, nonce: &str) -> PathBuf {
    let title = safe_filename(&artifact.title);
    let suffix = artifact
        .id
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .take(12)
        .collect::<String>();
    let ext = match artifact.media_type.as_str() {
        "text/markdown" => "md",
        "application/json" => "json",
        "text/x-code" => "txt",
        _ if artifact.kind == "report" => "md",
        _ => "txt",
    };
    dir.join(format!(
        "{title}-{}-{nonce}.{ext}",
        if suffix.is_empty() { "artifact" } else { &suffix }
    ))
}

fn safe_filename(title: &str) -> String {
    let cleaned = title
        .chars()
        .map(|c| {
            if c.is_alphanumeric() || matches!(c, '-' | '_' | ' ') {
                c
            } else {
                '_'
            }
        })
        .collect::<String>()
        .trim()
        .trim_matches('.')
        .chars()
        .take(80)
        .collect::<String>();
    if cleaned.is_empty() {
        "Vanta Artifact".into()
    } else {
        cleaned
    }
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

#[cfg(test)]
mod tests {
    use super::{export_path, safe_filename, ExportableArtifact};
    use std::path::Path;

    #[test]
    fn artifact_export_filename_cannot_escape_directory() {
        assert_eq!(safe_filename("../../秘密/report"), "______秘密_report");
        let artifact = ExportableArtifact {
            id: "art-123".into(),
            title: "../../report".into(),
            kind: "report".into(),
            media_type: "text/markdown".into(),
            sensitivity: "internal".into(),
            content: "body".into(),
        };
        assert_eq!(
            export_path(Path::new("/safe"), &artifact, "deadbeef"),
            Path::new("/safe/______report-art123-deadbeef.md")
        );
    }
}
