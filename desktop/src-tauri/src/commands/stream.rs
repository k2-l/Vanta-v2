//! 后端 SSE → Tauri Channel 桥。WebView 不接触后端 URL 或 JWT。

use crate::backend_gateway;
use crate::credentials;
use crate::error::{ClientError, CmdResult, ErrorKind};
use crate::state::AppState;
use futures_util::StreamExt;
use serde::Serialize;
use tauri::{ipc::Channel, State};

fn not_yet(gate: &str) -> ClientError {
    ClientError::new(ErrorKind::Desktop, format!("流式能力将在 {gate} 阶段接入"), false)
}

#[tauri::command]
pub async fn chat_start(
    state: State<'_, AppState>,
    connection_id: String,
    session_id: Option<String>,
    content: String,
    client_request_id: String,
    on_event: Channel<StreamPacket>,
) -> CmdResult<StreamHandle> {
    if content.trim().is_empty() {
        return Err(ClientError::validation("消息不能为空"));
    }

    let base_url = state.connections.resolve_base_url(&connection_id)?;
    let token = credentials::read_token(&connection_id)?
        .ok_or_else(|| ClientError::new(ErrorKind::Unauthorized, "未登录", false))?;
    let response = reqwest::Client::builder()
        .connect_timeout(std::time::Duration::from_secs(6))
        // 对话流可能持续很久，只给建连限时，不设整体请求超时。
        .user_agent("Vanta-Desktop/0.0.0")
        .build()
        .map_err(ClientError::from)?
        .post(format!("{base_url}/chat"))
        .bearer_auth(token)
        .header("X-Client-Request-Id", client_request_id)
        .json(&serde_json::json!({
            "message": content,
            "session_id": session_id,
            "execution_env": "local",
        }))
        .send()
        .await
        .map_err(ClientError::from)?;
    if !response.status().is_success() {
        return Err(backend_gateway::map_status(response.status()));
    }

    let handle_id = uuid::Uuid::new_v4().to_string();
    let channel_id = on_event.id();
    let (cancel_tx, mut cancel_rx) = tokio::sync::oneshot::channel();
    state.streams.insert(handle_id.clone(), cancel_tx);
    let registry = state.streams.clone();
    let task_handle = handle_id.clone();

    tauri::async_runtime::spawn(async move {
        let mut stream = response.bytes_stream();
        let mut buffer = Vec::<u8>::new();
        let mut reason = "completed";

        'streaming: loop {
            tokio::select! {
                _ = &mut cancel_rx => {
                    reason = "cancelled";
                    break;
                }
                next = stream.next() => match next {
                    Some(Ok(bytes)) => {
                        buffer.extend_from_slice(&bytes);
                        for frame in take_sse_frames(&mut buffer) {
                            if let Some(packet) = parse_sse_frame(&frame) {
                                if on_event.send(packet).is_err() {
                                    reason = "receiver_closed";
                                    break 'streaming;
                                }
                            }
                        }
                    }
                    Some(Err(err)) => {
                        let error = ClientError::from(err);
                        let _ = on_event.send(StreamPacket {
                            event: "client_error".into(),
                            data: serde_json::to_value(error).unwrap_or(serde_json::Value::Null),
                        });
                        reason = "failed";
                        break;
                    }
                    None => break,
                }
            }
        }

        let _ = on_event.send(StreamPacket {
            event: "stream.closed".into(),
            data: serde_json::json!({ "reason": reason }),
        });
        registry.remove(&task_handle);
    });

    Ok(StreamHandle { handle_id, run_id: None, channel_id })
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
pub async fn stream_stop(state: State<'_, AppState>, handle_id: String) -> CmdResult<()> {
    if let Some(cancel) = state.streams.remove(&handle_id) {
        let _ = cancel.send(());
    }
    Ok(())
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StreamPacket {
    pub event: String,
    pub data: serde_json::Value,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StreamHandle {
    pub handle_id: String,
    pub run_id: Option<String>,
    pub channel_id: u32,
}

fn take_sse_frames(buffer: &mut Vec<u8>) -> Vec<Vec<u8>> {
    let mut frames = Vec::new();
    while let Some((position, delimiter_len)) = find_frame_end(buffer) {
        let frame = buffer.drain(..position).collect();
        buffer.drain(..delimiter_len);
        frames.push(frame);
    }
    frames
}

fn find_frame_end(bytes: &[u8]) -> Option<(usize, usize)> {
    let lf = bytes.windows(2).position(|w| w == b"\n\n").map(|p| (p, 2));
    let crlf = bytes.windows(4).position(|w| w == b"\r\n\r\n").map(|p| (p, 4));
    match (lf, crlf) {
        (Some(a), Some(b)) => Some(if a.0 < b.0 { a } else { b }),
        (Some(found), None) | (None, Some(found)) => Some(found),
        (None, None) => None,
    }
}

fn parse_sse_frame(frame: &[u8]) -> Option<StreamPacket> {
    let text = String::from_utf8_lossy(frame);
    let mut event = "message".to_string();
    let mut data = Vec::new();
    for line in text.lines() {
        if let Some(value) = line.strip_prefix("event:") {
            event = value.trim().to_string();
        } else if let Some(value) = line.strip_prefix("data:") {
            data.push(value.trim_start());
        }
    }
    if data.is_empty() {
        return None;
    }
    let raw = data.join("\n");
    let data = serde_json::from_str(&raw).unwrap_or(serde_json::Value::String(raw));
    Some(StreamPacket { event, data })
}

#[cfg(test)]
mod tests {
    use super::{parse_sse_frame, take_sse_frames};

    #[test]
    fn parses_chunked_sse_frames() {
        let mut bytes = b"event: text_delta\r\ndata: {\"text\":\"hi\"}\r\n\r\nevent: done\ndata: {\"type\":\"done\"}\n\n".to_vec();
        let frames = take_sse_frames(&mut bytes);
        assert_eq!(frames.len(), 2);
        assert_eq!(parse_sse_frame(&frames[0]).unwrap().event, "text_delta");
        assert_eq!(parse_sse_frame(&frames[1]).unwrap().event, "done");
        assert!(bytes.is_empty());
    }
}
