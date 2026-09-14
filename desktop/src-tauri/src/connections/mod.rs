//! 连接 profile 管理（方案 §9.1）。
//!
//! - profile 为非敏感数据，持久化到 app data 目录的 JSON 文件；
//! - 凭据不在此模块，见 `credentials`；
//! - baseUrl 保存前标准化 scheme/host/port/path，并默认拒绝明文远程 HTTP（loopback 例外）。

use crate::error::{ClientError, CmdResult, ErrorKind};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Mutex;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TlsPolicy {
    System,
    CustomCa,
}

impl Default for TlsPolicy {
    fn default() -> Self {
        TlsPolicy::System
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConnectionProfile {
    pub id: String,
    pub label: String,
    pub base_url: String,
    #[serde(default)]
    pub tls_policy: TlsPolicy,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub last_connected_at: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub last_known_version: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConnectionDraft {
    #[serde(default)]
    pub id: Option<String>,
    pub label: String,
    pub base_url: String,
    #[serde(default)]
    pub tls_policy: Option<TlsPolicy>,
}

/// 标准化并校验后端地址。返回规整后的 `scheme://host[:port][/path]`（去尾斜杠）。
pub fn normalize_base_url(raw: &str) -> CmdResult<String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err(ClientError::validation("后端地址不能为空"));
    }
    let url = reqwest::Url::parse(trimmed)
        .map_err(|_| ClientError::validation("后端地址格式非法（需含 scheme，如 http:// 或 https://）"))?;

    match url.scheme() {
        "https" => {}
        "http" => {
            // 明文 HTTP 仅允许本机 loopback（开发例外），远程默认拒绝（方案 §9.1）。
            let host = url.host_str().unwrap_or_default();
            let is_loopback = host == "localhost" || host == "127.0.0.1" || host == "::1";
            if !is_loopback {
                return Err(ClientError::validation("拒绝明文远程 HTTP，请使用 HTTPS（本机 loopback 除外）"));
            }
        }
        other => return Err(ClientError::validation(format!("不支持的 scheme: {other}"))),
    }

    if url.host_str().is_none() {
        return Err(ClientError::validation("后端地址缺少 host"));
    }

    // 规整：保留 scheme/host/port 与 path，剥离 query/fragment 与尾斜杠。
    let mut base = format!(
        "{}://{}",
        url.scheme(),
        url.host_str().unwrap_or_default()
    );
    if let Some(port) = url.port() {
        base.push_str(&format!(":{port}"));
    }
    let path = url.path().trim_end_matches('/');
    if !path.is_empty() {
        base.push_str(path);
    }
    Ok(base)
}

/// profile 存储：内存缓存 + JSON 文件持久化，全程 Mutex 保护。
pub struct ConnectionStore {
    path: PathBuf,
    inner: Mutex<Vec<ConnectionProfile>>,
}

impl ConnectionStore {
    pub fn load(path: PathBuf) -> Self {
        let inner = std::fs::read(&path)
            .ok()
            .and_then(|bytes| serde_json::from_slice::<Vec<ConnectionProfile>>(&bytes).ok())
            .unwrap_or_default();
        Self {
            path,
            inner: Mutex::new(inner),
        }
    }

    fn persist(&self, list: &[ConnectionProfile]) -> CmdResult<()> {
        if let Some(dir) = self.path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        let bytes = serde_json::to_vec_pretty(list)?;
        std::fs::write(&self.path, bytes)?;
        Ok(())
    }

    pub fn list(&self) -> Vec<ConnectionProfile> {
        self.inner.lock().expect("connection store poisoned").clone()
    }

    pub fn get(&self, id: &str) -> Option<ConnectionProfile> {
        self.inner
            .lock()
            .expect("connection store poisoned")
            .iter()
            .find(|c| c.id == id)
            .cloned()
    }

    pub fn save(&self, draft: ConnectionDraft) -> CmdResult<ConnectionProfile> {
        let base_url = normalize_base_url(&draft.base_url)?;
        let mut guard = self.inner.lock().expect("connection store poisoned");
        let profile = match draft.id.as_ref().and_then(|id| guard.iter().position(|c| &c.id == id)) {
            Some(idx) => {
                let existing = &guard[idx];
                let updated = ConnectionProfile {
                    id: existing.id.clone(),
                    label: if draft.label.is_empty() { existing.label.clone() } else { draft.label },
                    base_url,
                    tls_policy: draft.tls_policy.unwrap_or(existing.tls_policy),
                    last_connected_at: existing.last_connected_at.clone(),
                    last_known_version: existing.last_known_version.clone(),
                };
                guard[idx] = updated.clone();
                updated
            }
            None => {
                let profile = ConnectionProfile {
                    id: uuid::Uuid::new_v4().to_string(),
                    label: if draft.label.is_empty() { base_url.clone() } else { draft.label },
                    base_url,
                    tls_policy: draft.tls_policy.unwrap_or_default(),
                    last_connected_at: None,
                    last_known_version: None,
                };
                guard.push(profile.clone());
                profile
            }
        };
        self.persist(&guard)?;
        Ok(profile)
    }

    pub fn delete(&self, id: &str) -> CmdResult<()> {
        let mut guard = self.inner.lock().expect("connection store poisoned");
        guard.retain(|c| c.id != id);
        self.persist(&guard)
    }

    /// 激活成功后回写 last_connected_at / last_known_version。
    pub fn mark_connected(&self, id: &str, version: Option<String>) -> CmdResult<()> {
        let mut guard = self.inner.lock().expect("connection store poisoned");
        if let Some(c) = guard.iter_mut().find(|c| c.id == id) {
            c.last_connected_at = Some(now_iso());
            if version.is_some() {
                c.last_known_version = version;
            }
        }
        self.persist(&guard)
    }

    pub fn resolve_base_url(&self, id: &str) -> CmdResult<String> {
        self.get(id)
            .map(|c| c.base_url)
            .ok_or_else(|| ClientError::new(ErrorKind::NotFound, "连接不存在", false))
    }
}

fn now_iso() -> String {
    // 轻量 ISO8601（UTC 秒级），避免引入 chrono。
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    format!("@{now}") // 占位：G1 引入 time crate 后替换为标准 RFC3339
}
