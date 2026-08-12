"""ExecEnv — session-level execution environment (local machine vs container).

Usage:
    from harness.tools.exec_context import get_exec_env, set_exec_env, ExecEnv

Tool nodes call set_exec_env() before dispatching tools; tools call get_exec_env()
transparently. The LLM never sees execution environment details.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


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
