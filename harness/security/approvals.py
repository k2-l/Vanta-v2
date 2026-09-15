"""工具审批门（HITL）：阻塞式人工审批的等待原语。

requires_approval=True 的工具在 execute_tool_core 执行前调用 request_approval()：
  1. 通过 event_bus 推送 approval_required 事件（WS /ws/chat/{session_id} 转发给前端）
  2. 创建一个 asyncio.Future，await 等待前端通过 REST 决策端点
     POST /chat/approvals/{call_id} 调用 resolve_approval() 写入结果
  3. 超时或异常均 fail-closed（视为拒绝）

纯内存实现，与 event_bus 同等可靠性模型：不持久化，进程重启会丢弃所有挂起的
审批请求（对应工具调用按"拒绝"处理）。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from harness.infra.event_bus import event_bus
from harness.infra.logging import log

DEFAULT_APPROVAL_TIMEOUT = 300.0  # 秒，与 actionable-improvements.md 原方案一致

_pending: dict[str, asyncio.Future[bool]] = {}
# 与 _pending 平行的元数据，供 GET /chat/approvals 列出待处理队列（桌面/Web HITL UI）。
_pending_meta: dict[str, dict] = {}


def list_pending() -> list[dict]:
    """当前进程内所有挂起的审批请求（最新在前）。纯内存，进程重启即清空。"""
    return sorted(_pending_meta.values(), key=lambda m: m["requested_at"], reverse=True)


# ── 风险 / 对象 / 范围 / 影响 派生（审批卡的权威信号来源）──────────────────
# 风险等级：工具显式声明（Tool.risk_level）优先，否则按 category 回退并标记为"派生"，
# 由前端如实展示，不伪称是工具声明（规范 §4.3：风险等级须有依据）。
_CATEGORY_RISK: dict[str, str] = {
    "exec": "high",  # 命令 / 代码执行
    "security": "high",  # 主动扫描 / 利用类
    "web": "medium",  # 出站抓取 / 探测
    "file": "medium",  # 文件读写
    "mcp": "medium",  # 外部 MCP 工具
}
_VALID_RISK = {"critical", "high", "medium", "low"}
# 从工具入参里挑选最能代表"操作对象"的键（按优先级）。
_TARGET_KEYS = (
    "command",
    "cmd",
    "url",
    "target",
    "host",
    "path",
    "file",
    "filename",
    "query",
    "pattern",
)
_IMPACT_BY_RISK: dict[str, str] = {
    "critical": "可造成破坏性或不可逆操作，务必确认授权范围",
    "high": "将对目标执行主动 / 写入类操作，需明确授权",
    "medium": "将访问外部资源或写入文件系统",
    "low": "影响有限（读取 / 编排类操作）",
}


def classify_risk(category: str, risk_level: str = "") -> tuple[str, str]:
    """返回 (等级, 来源)。来源为 "declared"（工具显式声明）或 "derived"（按 category 回退）。"""
    lvl = (risk_level or "").strip().lower()
    if lvl in _VALID_RISK:
        return lvl, "declared"
    return _CATEGORY_RISK.get(category, "low"), "derived"


def describe_target(tool_input: dict) -> str:
    """从入参提取"操作对象"：优先常见键，回退到入参键名列表。"""
    for k in _TARGET_KEYS:
        v = tool_input.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:200]
        if v not in (None, "", [], {}, ()):
            return str(v)[:200]
    return "、".join(sorted(tool_input.keys()))[:200] if tool_input else "（无参数）"


def describe_scope(*, kind: str = "local", container_id: str = "", engagement_id: str = "") -> str:
    """作用范围：执行位置（本机 / 隔离容器）+ 授权 engagement。"""
    where = "隔离容器" if kind == "container" else "本机"
    if kind == "container" and container_id:
        where = f"隔离容器 {container_id[:12]}"
    return (
        f"{where} · 授权范围 {engagement_id[:12]}"
        if engagement_id
        else f"{where} · 无活跃 engagement"
    )


def describe_impact(risk: str) -> str:
    """预计影响：按风险等级给出人可读描述。"""
    return _IMPACT_BY_RISK.get(risk, _IMPACT_BY_RISK["medium"])


async def request_approval(
    session_id: str,
    tool_name: str,
    message: str,
    *,
    risk: str = "",
    risk_source: str = "",
    target: str = "",
    scope: str = "",
    impact: str = "",
    timeout: float = DEFAULT_APPROVAL_TIMEOUT,  # noqa: ASYNC109 — 与 execute_tool_core 同款超时参数
) -> bool:
    """请求人工审批并阻塞等待决策。

    通过 event_bus 发布 approval_required 事件（call_id/tool_name/message），
    然后 await 一个 Future，直到 resolve_approval(call_id, ...) 被调用或超时。

    返回 True = 批准；False = 拒绝/超时/异常（fail-closed）。
    """
    call_id = uuid.uuid4().hex[:12]
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[bool] = loop.create_future()
    _pending[call_id] = fut
    now = datetime.now(UTC)
    _pending_meta[call_id] = {
        "call_id": call_id,
        "tool_name": tool_name,
        "message": message,
        "session_id": session_id,
        "risk": risk,
        "risk_source": risk_source,
        "target": target,
        "scope": scope,
        "impact": impact,
        "requested_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=timeout)).isoformat(),
    }

    try:
        await event_bus.publish(
            session_id,
            {
                "type": "approval_required",
                "call_id": call_id,
                "tool_name": tool_name,
                "message": message,
                "risk": risk,
                "risk_source": risk_source,
                "target": target,
                "scope": scope,
                "impact": impact,
            },
        )
        log.info("approval.requested", call_id=call_id, tool_name=tool_name, session_id=session_id)
        return await asyncio.wait_for(fut, timeout=timeout)
    except TimeoutError:
        log.warning("approval.timeout", call_id=call_id, tool_name=tool_name, session_id=session_id)
        return False
    except Exception as exc:  # noqa: BLE001 — fail-closed：任何异常都视为拒绝
        log.warning("approval.error", call_id=call_id, tool_name=tool_name, error=str(exc)[:200])
        return False
    finally:
        _pending.pop(call_id, None)
        _pending_meta.pop(call_id, None)


def resolve_approval(call_id: str, approved: bool) -> dict | None:
    """REST 决策端点调用：resolve 对应的 Future，并回传该请求的元数据快照。

    返回 None 表示 call_id 不存在或已被处理（前端应提示"该审批请求已失效"）。
    返回 dict 时包含请求元数据 + `decision`（approved/rejected），供路由写入审计账本。
    元数据在此处拷贝：set_result 会唤醒 request_approval 并在其 finally 弹出 _pending_meta，
    先拷贝可避免竞态。
    """
    fut = _pending.get(call_id)
    if fut is None or fut.done():
        return None
    meta = dict(_pending_meta.get(call_id, {}))
    fut.set_result(approved)
    meta["decision"] = "approved" if approved else "rejected"
    return meta
