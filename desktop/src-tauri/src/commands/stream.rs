//! 流式命令占位（chat_start / run_subscribe / stream_stop）。
//!
//! G0 不实现流式（方案 §19：G1 才接 SSE、G2 才接 run 订阅）。
//! 遵循「未实现的后端能力不在 GUI 伪装成可用」——此处显式返回未实现错误，
//! 而非静默成功。EventBridge / Channel 转发逻辑在 G1 落地。

use crate::error::{ClientError, CmdResult, ErrorKind};

fn not_yet(gate: &str) -> ClientError {
    ClientError::new(ErrorKind::Desktop, format!("流式能力将在 {gate} 阶段接入"), false)
}

#[tauri::command]
pub async fn chat_start(
    _connection_id: String,
    _session_id: String,
    _content: String,
    _client_request_id: String,
) -> CmdResult<serde_json::Value> {
    Err(not_yet("G1"))
}

#[tauri::command]
pub async fn run_subscribe(
    _connection_id: String,
    _run_id: String,
    _after_seq: Option<u64>,
) -> CmdResult<serde_json::Value> {
    Err(not_yet("G2"))
}

#[tauri::command]
pub async fn stream_stop(_handle_id: String) -> CmdResult<()> {
    Err(not_yet("G1"))
}
