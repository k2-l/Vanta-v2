"""Agent 和 Skill 改名时的文件及冲突边界。"""

from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from harness.agents.provider import AgentProvider
from harness.contracts.models import AgentFull, EntityMeta, SkillFull
from harness.routes import agents, skills
from harness.skills.provider import SkillProvider


class RenameManagementTests(unittest.IsolatedAsyncioTestCase):
    def _cases(self):
        return (
            (agents, AgentProvider, AgentFull, agents.AgentPatch, agents.update_agent),
            (skills, SkillProvider, SkillFull, skills.SkillPatch, skills.update_skill),
        )

    def _provider(self, root: Path, provider_type, full_type):
        provider = provider_type(root)
        provider.reload()
        provider.write(
            "old",
            full_type(
                meta=EntityMeta(
                    name="old",
                    description="original",
                    disable_model_invocation=True,
                    user_invocable=False,
                ),
                content="body",
            ),
        )
        return provider

    async def test_rename_preserves_content_and_invocation_flags(self) -> None:
        for module, provider_type, full_type, patch_type, update in self._cases():
            with self.subTest(kind=module.__name__), tempfile.TemporaryDirectory() as tmp:
                provider = self._provider(Path(tmp), provider_type, full_type)
                with ExitStack() as stack:
                    stack.enter_context(patch.object(module, "_provider", return_value=provider))
                    stack.enter_context(patch.object(module, "_invalidate_caches"))
                    if module is skills:
                        stack.enter_context(patch.object(skills, "_remove_skill_vector"))
                        stack.enter_context(patch.object(skills, "_sync_skill_vector"))
                    result = await update("old", patch_type(name="new"), {})

                self.assertEqual(result["name"], "new")
                self.assertEqual(result["content"], "body")
                self.assertTrue(result["disable_model_invocation"])
                self.assertFalse(result["user_invocable"])
                self.assertIsNone(provider.get("old"))
                self.assertIsNotNone(provider.get("new"))

    async def test_conflicting_rename_does_not_overwrite_target(self) -> None:
        for module, provider_type, full_type, patch_type, update in self._cases():
            with self.subTest(kind=module.__name__), tempfile.TemporaryDirectory() as tmp:
                provider = self._provider(Path(tmp), provider_type, full_type)
                provider.write(
                    "taken",
                    full_type(meta=EntityMeta(name="taken", description="target"), content="keep"),
                )
                with patch.object(module, "_provider", return_value=provider):
                    with self.assertRaises(HTTPException) as raised:
                        await update("old", patch_type(name="taken"), {})

                self.assertEqual(raised.exception.status_code, 409)
                self.assertEqual(provider.get("old").content, "body")
                self.assertEqual(provider.get("taken").content, "keep")

    async def test_failed_rename_write_keeps_original(self) -> None:
        for module, provider_type, full_type, patch_type, update in self._cases():
            with self.subTest(kind=module.__name__), tempfile.TemporaryDirectory() as tmp:
                provider = self._provider(Path(tmp), provider_type, full_type)
                with (
                    patch.object(module, "_provider", return_value=provider),
                    patch.object(provider, "write", side_effect=OSError("write failed")),
                    patch.object(provider, "delete") as delete,
                ):
                    with self.assertRaises(OSError):
                        await update("old", patch_type(name="new"), {})

                delete.assert_not_called()
                self.assertEqual(provider.get("old").content, "body")
                self.assertIsNone(provider.get("new"))

    async def test_agent_patch_updates_existing_invocation_controls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = self._provider(Path(tmp), AgentProvider, AgentFull)
            with (
                patch.object(agents, "_provider", return_value=provider),
                patch.object(agents, "_invalidate_caches"),
            ):
                result = await agents.update_agent(
                    "old",
                    agents.AgentPatch(
                        disable_model_invocation=False,
                        user_invocable=True,
                    ),
                    {},
                )

            self.assertFalse(result["disable_model_invocation"])
            self.assertTrue(result["user_invocable"])
            updated = provider.get("old")
            self.assertFalse(updated.meta.disable_model_invocation)
            self.assertTrue(updated.meta.user_invocable)

    async def test_agent_register_does_not_overwrite_existing_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = self._provider(Path(tmp), AgentProvider, AgentFull)
            with patch.object(agents, "_provider", return_value=provider):
                with self.assertRaises(HTTPException) as raised:
                    await agents.register_agent(
                        agents.RegisterAgentRequest(
                            md="---\nname: old\ndescription: replacement\n---\nreplace"
                        ),
                        {},
                    )

            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(provider.get("old").content, "body")


if __name__ == "__main__":
    unittest.main()
