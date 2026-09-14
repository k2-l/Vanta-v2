//! 归一化客户端错误（方案 §8.3）——与前端 `contracts/errors.ts` 的 ClientError 同构。
//!
//! 所有 `#[tauri::command]` 返回 `Result<T, ClientError>`；序列化为 camelCase JSON。

use serde::Serialize;

#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ErrorKind {
    Offline,
    Timeout,
    Unauthorized,
    Forbidden,
    NotFound,
    Conflict,
    Validation,
    Protocol,
    Backend,
    Desktop,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ClientError {
    pub kind: ErrorKind,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub code: Option<String>,
    pub message: String,
    pub retryable: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub request_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub details: Option<serde_json::Value>,
}

impl ClientError {
    pub fn new(kind: ErrorKind, message: impl Into<String>, retryable: bool) -> Self {
        Self {
            kind,
            code: None,
            message: message.into(),
            retryable,
            request_id: None,
            details: None,
        }
    }

    pub fn desktop(message: impl Into<String>) -> Self {
        Self::new(ErrorKind::Desktop, message, false)
    }

    pub fn validation(message: impl Into<String>) -> Self {
        Self::new(ErrorKind::Validation, message, false)
    }

    pub fn offline(message: impl Into<String>) -> Self {
        Self::new(ErrorKind::Offline, message, true)
    }

    pub fn with_code(mut self, code: impl Into<String>) -> Self {
        self.code = Some(code.into());
        self
    }

    pub fn with_request_id(mut self, id: impl Into<String>) -> Self {
        self.request_id = Some(id.into());
        self
    }
}

/// reqwest 错误归一化（网络层）。
impl From<reqwest::Error> for ClientError {
    fn from(err: reqwest::Error) -> Self {
        if err.is_timeout() {
            ClientError::new(ErrorKind::Timeout, "请求超时", true)
        } else if err.is_connect() {
            ClientError::offline("无法连接后端")
        } else if err.is_decode() {
            ClientError::new(ErrorKind::Protocol, "响应解析失败", false)
        } else {
            ClientError::new(ErrorKind::Backend, err.to_string(), false)
        }
    }
}

impl From<serde_json::Error> for ClientError {
    fn from(err: serde_json::Error) -> Self {
        ClientError::new(ErrorKind::Protocol, format!("JSON 错误: {err}"), false)
    }
}

impl From<std::io::Error> for ClientError {
    fn from(err: std::io::Error) -> Self {
        ClientError::desktop(format!("IO 错误: {err}"))
    }
}

pub type CmdResult<T> = Result<T, ClientError>;
