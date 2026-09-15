//! 连接 profile 管理（方案 §9.1）。
//!
//! - profile 为非敏感数据，持久化到 app data 目录的 JSON 文件；
//! - 凭据不在此模块，见 `credentials`；
//! - baseUrl 保存前标准化 scheme/host/port/path；开发联调允许本机及远程 HTTP，上线使用 HTTPS。

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
    /// custom_ca 策略下的 CA 证书文件路径（PEM）；供 reqwest 追加信任根，
    /// 免去把自签证书装进系统信任库。仅在 tls_policy=custom_ca 时生效。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ca_cert_path: Option<String>,
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
    #[serde(default)]
    pub ca_cert_path: Option<String>,
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
        // 开发联调允许远程 HTTP；HTTPS 仍使用原有证书校验。
        "http" | "https" => {}
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
                let tls_policy = draft.tls_policy.unwrap_or(existing.tls_policy);
                // 草稿未带 ca_cert_path 时沿用旧值；切回 system 策略则清空。
                let ca_cert_path = match tls_policy {
                    TlsPolicy::CustomCa => draft.ca_cert_path.or_else(|| existing.ca_cert_path.clone()),
                    TlsPolicy::System => None,
                };
                let updated = ConnectionProfile {
                    id: existing.id.clone(),
                    label: if draft.label.is_empty() { existing.label.clone() } else { draft.label },
                    base_url,
                    tls_policy,
                    ca_cert_path,
                    last_connected_at: existing.last_connected_at.clone(),
                    last_known_version: existing.last_known_version.clone(),
                };
                guard[idx] = updated.clone();
                updated
            }
            None => {
                let tls_policy = draft.tls_policy.unwrap_or_default();
                let ca_cert_path = match tls_policy {
                    TlsPolicy::CustomCa => draft.ca_cert_path,
                    TlsPolicy::System => None,
                };
                let profile = ConnectionProfile {
                    id: uuid::Uuid::new_v4().to_string(),
                    label: if draft.label.is_empty() { base_url.clone() } else { draft.label },
                    base_url,
                    tls_policy,
                    ca_cert_path,
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

    /// 仅 HTTPS + custom_ca 返回证书路径；HTTP 忽略历史 TLS 配置。
    pub fn resolve_ca(&self, id: &str) -> Option<String> {
        self.get(id)
            .filter(|c| c.base_url.starts_with("https://"))
            .and_then(|c| match c.tls_policy {
                TlsPolicy::CustomCa => c.ca_cert_path,
                TlsPolicy::System => None,
            })
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_remote_http_for_development() {
        assert_eq!(
            normalize_base_url(" http://10.1.1.2:8765/ ").unwrap(),
            "http://10.1.1.2:8765"
        );
    }

    #[test]
    fn retains_https_and_rejects_other_protocols() {
        assert_eq!(
            normalize_base_url("https://backend.example.test/api/").unwrap(),
            "https://backend.example.test/api"
        );
        assert!(normalize_base_url("ftp://backend.example.test").is_err());
        assert!(normalize_base_url("").is_err());
    }

    #[test]
    fn http_ignores_saved_ca_but_https_retains_it() {
        let http = ConnectionProfile {
            id: "http".into(),
            label: "Development".into(),
            base_url: "http://10.1.1.2:8765".into(),
            tls_policy: TlsPolicy::CustomCa,
            ca_cert_path: Some("old-certificate.pem".into()),
            last_connected_at: None,
            last_known_version: None,
        };
        let https = ConnectionProfile {
            id: "https".into(),
            base_url: "https://10.1.1.2:8765".into(),
            ..http.clone()
        };
        let store = ConnectionStore {
            path: PathBuf::new(),
            inner: Mutex::new(vec![http, https]),
        };
        assert_eq!(store.resolve_ca("http"), None);
        assert_eq!(store.resolve_ca("https").as_deref(), Some("old-certificate.pem"));
    }
}
