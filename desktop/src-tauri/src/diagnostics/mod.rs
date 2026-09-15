//! 诊断与脱敏（方案 §17、§14.2）。
//!
//! 对已知敏感标记做有限脱敏；不能代替分享前的人工检查。

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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redacts_bearer() {
        let s = redact("GET /x Authorization: Bearer abc.def.ghi next");
        assert!(!s.contains("abc.def.ghi"));
    }
}
