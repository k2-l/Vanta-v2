"""engagement scope 分类归一回归测试。

背景：会话 cc82ee1e9c79 里 engagement(create) 因传入带 scheme/端口的 target
（http://host:10800、host:10800）被判「targets 全部非法」而两次失败——而运行时
target_in_scope 却会 normalize_host 后正常匹配（自相矛盾）。本测试锁定修复：
create 侧对 URL / host:port 先分类归一为裸 host 再校验，同时保留 CIDR 掩码与 repo: 前缀。
"""

from __future__ import annotations

import unittest

from harness.security.engagement import validate_scope


class ValidateScopeNormalizationTests(unittest.TestCase):
    def test_url_with_scheme_and_port_is_normalized_and_accepted(self) -> None:
        # 会话 cc82ee1e9c79 seq 266 的原始失败输入
        valid, invalid = validate_scope(
            ["http://challenge-16da786f74da7dbc.sandbox.ctfhub.com:10800"]
        )
        self.assertEqual(valid, ["challenge-16da786f74da7dbc.sandbox.ctfhub.com"])
        self.assertEqual(invalid, [])

    def test_host_with_port_is_normalized_and_accepted(self) -> None:
        # 会话 cc82ee1e9c79 seq 394 的原始失败输入
        valid, invalid = validate_scope(
            ["challenge-16da786f74da7dbc.sandbox.ctfhub.com:10800"]
        )
        self.assertEqual(valid, ["challenge-16da786f74da7dbc.sandbox.ctfhub.com"])
        self.assertEqual(invalid, [])

    def test_bare_domain_unchanged(self) -> None:
        valid, invalid = validate_scope(["example.com"])
        self.assertEqual(valid, ["example.com"])
        self.assertEqual(invalid, [])

    def test_cidr_mask_preserved(self) -> None:
        # 归一化不得剥掉 CIDR 掩码
        valid, invalid = validate_scope(["10.0.0.0/24"])
        self.assertEqual(valid, ["10.0.0.0/24"])
        self.assertEqual(invalid, [])

    def test_plain_ipv4_accepted(self) -> None:
        valid, invalid = validate_scope(["192.168.1.5"])
        self.assertEqual(valid, ["192.168.1.5"])
        self.assertEqual(invalid, [])

    def test_repo_prefix_preserved(self) -> None:
        # repo: 前缀含 '/'，不能被当 URL 剥路径
        valid, invalid = validate_scope(["repo:github.com/foo/bar"])
        self.assertEqual(valid, ["repo:github.com/foo/bar"])
        self.assertEqual(invalid, [])

    def test_bracketed_ipv6_with_port_normalized(self) -> None:
        valid, invalid = validate_scope(["[2001:db8::1]:443"])
        self.assertEqual(valid, ["2001:db8::1"])
        self.assertEqual(invalid, [])

    def test_invalid_entries_reported_with_original_form(self) -> None:
        valid, invalid = validate_scope(["nodot", ""])
        self.assertEqual(valid, [])
        self.assertIn("nodot", invalid)
        self.assertIn("", invalid)

    def test_mixed_batch_partitions_and_normalizes(self) -> None:
        valid, invalid = validate_scope(
            ["https://a.b.com:8443/path?q=1", "10.0.0.0/24", "nodot"]
        )
        self.assertEqual(valid, ["a.b.com", "10.0.0.0/24"])
        self.assertEqual(invalid, ["nodot"])


if __name__ == "__main__":
    unittest.main()
