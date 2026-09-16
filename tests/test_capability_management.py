"""能力管理（文件驱动 provider）安全回归：实体名不得穿越 root。

覆盖 register / rename / delete 经 name 做路径穿越、绝对路径、空名与符号链接逃逸，
确保写入与 rmtree 都被限制在 <skills_dir>/<agents_dir> 之内。
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness.app.main import ensure_workspace
from harness.contracts.frontmatter import (
    delete_entity,
    validate_entity_name,
    write_entity,
)
from harness.contracts.models import EntityMeta, SkillFull
from harness.providers import get_provider


def _skill(name: str) -> SkillFull:
    return SkillFull(meta=EntityMeta(name=name, description="d"), content="body")


class EntityNameValidationTests(unittest.TestCase):
    def test_valid_names_pass(self) -> None:
        for n in ("java-audit", "audit_sqli", "Skill1", "v1.2", "a"):
            self.assertEqual(validate_entity_name(n), n)

    def test_name_is_stripped(self) -> None:
        self.assertEqual(validate_entity_name("  legit  "), "legit")

    def test_traversal_absolute_empty_and_overlong_rejected(self) -> None:
        bad = [
            "..", ".", "../x", "..\\x", "a/b", "a\\b", "/etc/passwd",
            "", "   ", ".hidden", "-lead", "with space", "a" * 65,
        ]
        for name in bad:
            with self.assertRaises(ValueError, msg=name):
                validate_entity_name(name)


class ProviderPathSafetyTests(unittest.TestCase):
    def test_write_delete_reject_traversal_and_stay_in_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"VANTA_ROOT": tmp}):
            ensure_workspace()
            p = get_provider("skill")
            root = Path(p.root)

            # 穿越写入被拒，且 root 外无残留
            with self.assertRaises(ValueError):
                p.write("../../pwn", _skill("../../pwn"))
            self.assertFalse((root.parent.parent / "pwn").exists())

            # 合法写入落在 root 内
            p.write("legit", _skill("legit"))
            self.assertTrue((root / "legit" / "SKILL.md").is_file())

            # 穿越删除被拒；原实体不受影响
            with self.assertRaises(ValueError):
                p.delete("../../legit")
            self.assertTrue((root / "legit").is_dir())

            # 合法删除
            self.assertTrue(p.delete("legit"))
            self.assertFalse((root / "legit").exists())

    def test_write_entity_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills"
            root.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            # 名字合法但目录是指向 root 外的符号链接——边界兜底须拦下
            (root / "evil").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                write_entity(root, "evil", "SKILL.md", _skill("evil"))
            self.assertEqual(list(outside.iterdir()), [])

    def test_delete_entity_missing_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills"
            root.mkdir()
            self.assertFalse(delete_entity(root, "nope"))


if __name__ == "__main__":
    unittest.main()
