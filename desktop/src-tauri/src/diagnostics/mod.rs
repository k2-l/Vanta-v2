//! 诊断与脱敏（方案 §17、§14.2）。
//!
//! 日志中禁止出现 Authorization / token / secret 正文；此处提供结构化脱敏。

/// 对可能含敏感信息的字符串做粗粒度脱敏（用于日志/诊断包）。
pub fn redact(input: &str) -> String {
    let mut out = input.to_string();
    for marker in ["Bearer ", "token=", "password=", "api_key=", "authorization:"] {
        if let Some(pos) = out.to_lowercase().find(&marker.to_lowercase()) {
            let value_start = pos + marker.len();
            let end = out[value_start..]
                .find(|c: char| c.is_whitespace() || c == '&' || c == '"')
                .map(|e| value_start + e)
                .unwrap_or(out.len());
            if end > value_start {
                out.replace_range(value_start..end, "<redacted>");
            }
        }
    }
    out
}

/// 诊断快照——不含任何凭据（方案 §17）。
#[derive(Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Diagnostics {
    pub app_version: String,
    pub platform: String,
    pub active_connection: Option<String>,
    pub server_version: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redacts_bearer() {
        let s = redact("GET /x Authorization: Bearer abc.def.ghi next");
        assert!(!s.contains("abc.def.ghi"));
    }
}
