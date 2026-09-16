//! 后端 SSE → Tauri Channel 桥。WebView 不接触后端 URL 或 JWT。

use crate::backend_gateway;
use crate::credentials;
use crate::error::{ClientError, CmdResult, ErrorKind};
use crate::state::AppState;
use futures_util::StreamExt;
use serde::Serialize;
use tauri::{ipc::Channel, State};

fn err_packet(err: ClientError) -> StreamPacket {
    StreamPacket {
        event: "client_error".into(),
        data: serde_json::to_value(err).unwrap_or(serde_json::Value::Null),
    }
}

/// phases 快照的终态结果。空快照仍可能是刚创建、尚未写入第一个 phase 的运行。
fn phases_terminal_reason(value: &serde_json::Value) -> Option<&'static str> {
    let rows = value.as_array()?;
    if rows.is_empty()
        || rows.iter().any(|p| {
            matches!(p.get("status").and_then(|s| s.as_str()), Some("running") | Some("pending"))
        })
    {
        return None;
    }
    if rows.iter().any(|p| p.get("status").and_then(|s| s.as_str()) == Some("failed")) {
        Some("failed")
    } else {
        Some("completed")
    }
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
    let ca = state.connections.resolve_ca(&connection_id);
    let mut token = credentials::read_token(&connection_id)?
        .ok_or_else(|| ClientError::new(ErrorKind::Unauthorized, "未登录", false))?;
    // 对话流可能持续很久，只给建连限时，不设整体请求超时（overall_timeout=None）。
    let client = backend_gateway::build_client(ca.as_deref(), None)?;
    let body = serde_json::json!({
        "message": content,
        "session_id": session_id,
        "execution_env": "local",
    });
    let mut response = client
        .post(format!("{base_url}/chat"))
        .bearer_auth(&token)
        .header("X-Client-Request-Id", &client_request_id)
        .json(&body)
        .send()
        .await
        .map_err(ClientError::from)?;
    if response.status() == reqwest::StatusCode::UNAUTHORIZED {
        backend_gateway::refresh(&base_url, &connection_id, ca.as_deref()).await?;
        token = credentials::read_token(&connection_id)?
            .ok_or_else(|| ClientError::new(ErrorKind::Unauthorized, "登录已失效", false))?;
        response = client
            .post(format!("{base_url}/chat"))
            .bearer_auth(&token)
            .header("X-Client-Request-Id", &client_request_id)
            .json(&body)
            .send()
            .await
            .map_err(ClientError::from)?;
    }
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

/// 订阅运行（Plan G2）——后端无 seq 事件流，故以 phases 快照轮询近似「实时」观察：
/// 拉取 `/sessions/{id}/phases`，作为 `snapshot` 包（携带自增 seq）转发，直到阶段全部终态
/// 或客户端停止。前端按 phase id 幂等对账、断线后重新订阅（重拉快照而非按序重放）。
#[tauri::command]
pub async fn run_subscribe(
    state: State<'_, AppState>,
    connection_id: String,
    run_id: String,
    after_seq: Option<u64>,
    on_event: Channel<StreamPacket>,
) -> CmdResult<StreamHandle> {
    let base_url = state.connections.resolve_base_url(&connection_id)?;
    let ca = state.connections.resolve_ca(&connection_id);
    let token = credentials::read_token(&connection_id)?
        .ok_or_else(|| ClientError::new(ErrorKind::Unauthorized, "未登录", false))?;
    let client = backend_gateway::build_client(ca.as_deref(), Some(std::time::Duration::from_secs(20)))?;

    let handle_id = uuid::Uuid::new_v4().to_string();
    let channel_id = on_event.id();
    let (cancel_tx, mut cancel_rx) = tokio::sync::oneshot::channel();
    state.streams.insert(handle_id.clone(), cancel_tx);
    let registry = state.streams.clone();
    let task_handle = handle_id.clone();
    let phases_url = format!("{base_url}/sessions/{run_id}/phases");
    let mut seq = after_seq.unwrap_or(0);

    tauri::async_runtime::spawn(async move {
        let mut token = token;
        let mut refreshed_after_unauthorized = false;
        // Channel 关闭或页面卸载时 send/stream_stop 会结束循环，无需把长运行误判为完成。
        let reason = 'polling: loop {
            match client.get(&phases_url).bearer_auth(&token).send().await {
                Ok(resp) if resp.status().is_success() => match resp.json::<serde_json::Value>().await {
                    Ok(value) => {
                        refreshed_after_unauthorized = false;
                        seq += 1;
                        let packet = StreamPacket {
                            event: "snapshot".into(),
                            data: serde_json::json!({ "phases": value, "seq": seq }),
                        };
                        if on_event.send(packet).is_err() {
                            break 'polling "receiver_closed";
                        }
                        if let Some(terminal_reason) = phases_terminal_reason(&value) {
                            break 'polling terminal_reason;
                        }
                    }
                    Err(err) => {
                        let _ = on_event.send(err_packet(ClientError::from(err)));
                        break 'polling "failed";
                    }
                },
                Ok(resp) if resp.status() == reqwest::StatusCode::UNAUTHORIZED && !refreshed_after_unauthorized => {
                    match backend_gateway::refresh(&base_url, &connection_id, ca.as_deref()).await {
                        Ok(_) => match credentials::read_token(&connection_id) {
                            Ok(Some(new_token)) => {
                                token = new_token;
                                refreshed_after_unauthorized = true;
                                continue;
                            }
                            Ok(None) => {
                                let _ = on_event.send(err_packet(ClientError::new(
                                    ErrorKind::Unauthorized,
                                    "登录已失效",
                                    false,
                                )));
                                break 'polling "failed";
                            }
                            Err(err) => {
                                let _ = on_event.send(err_packet(err));
                                break 'polling "failed";
                            }
                        },
                        Err(err) => {
                            let _ = on_event.send(err_packet(err));
                            break 'polling "failed";
                        }
                    }
                }
                Ok(resp) => {
                    let _ = on_event.send(err_packet(backend_gateway::map_status(resp.status())));
                    break 'polling "failed";
                }
                Err(err) => {
                    let _ = on_event.send(err_packet(ClientError::from(err)));
                    break 'polling "failed";
                }
            }
            tokio::select! {
                _ = &mut cancel_rx => { break 'polling "cancelled"; }
                _ = tokio::time::sleep(std::time::Duration::from_millis(1500)) => {}
            }
        };

        let _ = on_event.send(StreamPacket {
            event: "stream.closed".into(),
            data: serde_json::json!({ "reason": reason }),
        });
        registry.remove(&task_handle);
    });

    Ok(StreamHandle { handle_id, run_id: Some(run_id), channel_id })
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
    use super::{parse_sse_frame, phases_terminal_reason, take_sse_frames};

    #[test]
    fn parses_chunked_sse_frames() {
        let mut bytes = b"event: text_delta\r\ndata: {\"text\":\"hi\"}\r\n\r\nevent: done\ndata: {\"type\":\"done\"}\n\n".to_vec();
        let frames = take_sse_frames(&mut bytes);
        assert_eq!(frames.len(), 2);
        assert_eq!(parse_sse_frame(&frames[0]).unwrap().event, "text_delta");
        assert_eq!(parse_sse_frame(&frames[1]).unwrap().event, "done");
        assert!(bytes.is_empty());
    }

    #[test]
    fn phase_terminal_reason_distinguishes_empty_running_and_failed() {
        assert_eq!(phases_terminal_reason(&serde_json::json!([])), None);
        assert_eq!(
            phases_terminal_reason(&serde_json::json!([{ "status": "running" }])),
            None
        );
        assert_eq!(
            phases_terminal_reason(&serde_json::json!([{ "status": "ok" }])),
            Some("completed")
        );
        assert_eq!(
            phases_terminal_reason(&serde_json::json!([{ "status": "ok" }, { "status": "failed" }])),
            Some("failed")
        );
    }
}
