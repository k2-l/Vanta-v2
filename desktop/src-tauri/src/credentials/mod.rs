//! 凭据保管库（方案 §9.1、§14.2）。
//!
//! JWT / 刷新令牌 / API Key / 口令只存系统钥匙串（keyring），永不回传 WebView。
//! 前端只见到 `AuthSummary { authenticated, expiresAt, refreshExpiresAt }`。

use crate::error::{ClientError, CmdResult, ErrorKind};
use keyring::Entry;

const SERVICE: &str = "app.vanta.desktop";

fn entry(connection_id: &str, slot: &str) -> CmdResult<Entry> {
    Entry::new(SERVICE, &format!("{connection_id}:{slot}"))
        .map_err(|e| ClientError::desktop(format!("钥匙串不可用: {e}")))
}

/// 保存某连接的短期访问令牌（覆盖旧值）。
pub fn store_token(connection_id: &str, token: &str) -> CmdResult<()> {
    entry(connection_id, "jwt")?
        .set_password(token)
        .map_err(|e| ClientError::desktop(format!("凭据写入失败: {e}")))
}

/// 保存刷新令牌；只由 Rust Core 读取，永不回传 WebView。
pub fn store_refresh_token(connection_id: &str, token: &str) -> CmdResult<()> {
    entry(connection_id, "refresh")?
        .set_password(token)
        .map_err(|e| ClientError::desktop(format!("刷新凭据写入失败: {e}")))
}

pub fn store_token_pair(connection_id: &str, access: &str, refresh: &str) -> CmdResult<()> {
    store_token(connection_id, access)?;
    if let Err(error) = store_refresh_token(connection_id, refresh) {
        if let Ok(access_entry) = entry(connection_id, "jwt") {
            let _ = access_entry.delete_credential();
        }
        return Err(error);
    }
    Ok(())
}

/// 读取某连接的 JWT，供 BackendGateway 注入 Authorization 头。
pub fn read_token(connection_id: &str) -> CmdResult<Option<String>> {
    match entry(connection_id, "jwt")?.get_password() {
        Ok(t) => Ok(Some(t)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(e) => Err(ClientError::new(
            ErrorKind::Desktop,
            format!("凭据读取失败: {e}"),
            false,
        )),
    }
}

pub fn read_refresh_token(connection_id: &str) -> CmdResult<Option<String>> {
    match entry(connection_id, "refresh")?.get_password() {
        Ok(token) => Ok(Some(token)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(e) => Err(ClientError::new(
            ErrorKind::Desktop,
            format!("刷新凭据读取失败: {e}"),
            false,
        )),
    }
}

/// 清除某连接的凭据（登出 / 删除连接）。
pub fn clear(connection_id: &str) -> CmdResult<()> {
    let mut first_error = None;
    for slot in ["jwt", "refresh"] {
        match entry(connection_id, slot)?.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => {}
            Err(error) if first_error.is_none() => first_error = Some(error),
            Err(_) => {}
        }
    }
    match first_error {
        Some(error) => Err(ClientError::desktop(format!("凭据清除失败: {error}"))),
        None => Ok(()),
    }
}
