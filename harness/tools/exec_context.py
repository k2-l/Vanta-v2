"""ExecEnv — session-level execution environment (local machine vs container).

Usage:
    from harness.tools.exec_context import get_exec_env, set_exec_env, ExecEnv

Tool nodes call set_exec_env() before dispatching tools; tools call get_exec_env()
transparently. The LLM never sees execution environment details.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from harness.infra.logging import log
from harness.security.engagement import Engagement, is_engagement_active


@dataclass
class ExecEnv:
    kind: str = "local"      # "local" | "container"
    container_id: str = ""   # ContainerRecord 记录 ID（非 podman 容器 ID）
    # 活跃 engagement（scope 门 / 沙箱路由用）；空=无 engagement，主动扫描类动作应被拒
    engagement_id: str = ""
    scope_targets: tuple[str, ...] = ()   # 该 engagement 的授权 scope（tuple 可哈希/不可变）
    dns_resolver_ip: str = ""             # 沙箱可选受控 DNS resolver
    session_id: str = ""                  # 当前会话 id（engagement 工具据此绑定活跃 engagement）

    @property
    def is_local(self) -> bool:
        return self.kind == "local"

    @property
    def is_container(self) -> bool:
        return self.kind == "container"

    @property
    def has_engagement(self) -> bool:
        return bool(self.engagement_id)


_LOCAL_ENV: ExecEnv = ExecEnv(kind="local")
_exec_env: ContextVar[ExecEnv] = ContextVar("_exec_env", default=_LOCAL_ENV)


def get_exec_env() -> ExecEnv:
    return _exec_env.get()


def set_exec_env(env: ExecEnv) -> None:
    _exec_env.set(env)


def apply_exec_env(execution_env: str | None) -> None:
    """根据 state 的 execution_env 字符串设置当前 ExecEnv ContextVar。

    "container:<id>" → 容器环境；其余（含 None/""）→ 本地。
    主图与子图 tool_node 共用，消除两处逐字重复的环境传播块。
    """
    env_str = execution_env or "local"
    if env_str.startswith("container:"):
        set_exec_env(ExecEnv(kind="container", container_id=env_str.split(":", 1)[1]))
    else:
        set_exec_env(ExecEnv(kind="local"))


def apply_engagement(
    engagement_id: str,
    scope_targets: tuple[str, ...] | list[str] = (),
    dns_resolver_ip: str = "",
    session_id: str | None = None,
) -> None:
    """把活跃 engagement 叠加到当前 ExecEnv（保留 kind/container_id；session_id=None 时保留）。

    在 apply_exec_env 之后调用：tool_node 从 session 的活跃 engagement 读出 scope，
    使工具执行时能拿到"当前授权范围"。engagement_id 空串 = 清除（无活跃 engagement）。
    """
    cur = get_exec_env()
    set_exec_env(
        ExecEnv(
            kind=cur.kind,
            container_id=cur.container_id,
            engagement_id=engagement_id or "",
            scope_targets=tuple(scope_targets or ()),
            dns_resolver_ip=dns_resolver_ip or "",
            session_id=cur.session_id if session_id is None else session_id,
        )
    )


async def apply_active_engagement(session_id: str) -> None:
    """加载并验证会话授权后叠加到 ExecEnv；失效、缺失或异常时一律清空。"""
    if not session_id:
        apply_engagement("", session_id="")
        return

    try:
        from harness.infra.db import (
            get_active_engagement_id,
            get_engagement,
            set_active_engagement,
        )

        engagement_id = await get_active_engagement_id(session_id)
        record = await get_engagement(engagement_id) if engagement_id else None
        if record is None:
            apply_engagement("", session_id=session_id)
            return

        active, reason = is_engagement_active(
            Engagement(
                id=record.id,
                name=record.name,
                scope_targets=list(record.scope_targets or ()),
                status=record.status,
                authorization_ref=record.authorization_ref or "",
                starts_at=record.starts_at,
                ends_at=record.ends_at,
            )
        )
        if not active:
            await set_active_engagement(session_id, "")
            log.warning(
                "tool_node.engagement_inactive",
                session_id=session_id,
                engagement_id=record.id,
                reason=reason,
            )
            apply_engagement("", session_id=session_id)
            return

        apply_engagement(
            record.id,
            tuple(record.scope_targets or ()),
            record.dns_resolver_ip or "",
            session_id=session_id,
        )
    except Exception as exc:  # noqa: BLE001 -- 授权加载失败必须 fail-closed
        log.warning("tool_node.engagement_load_failed", session_id=session_id, exc=str(exc)[:200])
        apply_engagement("", session_id=session_id)
