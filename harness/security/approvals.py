"""工具审批门（HITL）：阻塞式人工审批的等待原语。

requires_approval=True 的工具在 execute_tool_core 执行前调用 request_approval()：
  1. 通过 event_bus 推送 approval_required 事件（WS /ws/chat/{session_id} 转发给前端）
  2. 创建一个 asyncio.Future，await 等待前端通过 REST 决策端点；决策端先认领请求、
     持久化审批历史，再唤醒 Future
  3. 超时或异常均 fail-closed（视为拒绝）

挂起队列与 Future 仍是进程内状态，进程重启会按 fail-closed 中止等待中的工具；
已决策/已过期结果持久化到 approval_history，并以哈希链作为审计证据。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from harness.infra import db
from harness.infra.event_bus import event_bus
from harness.infra.logging import log
from harness.security.audit_ledger import append_audit

DEFAULT_APPROVAL_TIMEOUT = 300.0  # 秒，与 actionable-improvements.md 原方案一致

_pending: dict[str, asyncio.Future[bool]] = {}
# 与 _pending 平行的元数据，供 GET /chat/approvals 列出待处理队列（桌面/Web HITL UI）。
_pending_meta: dict[str, dict] = {}
_claimed: set[str] = set()


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


async def _record_expired_approval(call_id: str, meta: dict[str, str]) -> None:
    """持久化过期决策并写审计账本；审计失败仍由调用方拒绝工具执行。"""
    decision_id = uuid.uuid4().hex
    history_saved = False
    try:
        await db.save_approval_history(
            decision_id=decision_id,
            call_id=call_id,
            tool_name=meta["tool_name"],
            session_id=meta["session_id"],
            actor="system",
            decision="expired",
            risk=meta["risk"],
            risk_source=meta["risk_source"],
            target=meta["target"],
            scope=meta["scope"],
            impact=meta["impact"],
            message=meta["message"],
            requested_at=meta["requested_at"],
            expires_at=meta["expires_at"],
        )
        history_saved = True
    except Exception as exc:  # noqa: BLE001 — 审批仍须 fail-closed
        log.warning("approval.expiry_history_failed", call_id=call_id, exc=str(exc)[:200])

    entry_hash = await append_audit(
        "tool_approval",
        session_id=meta["session_id"],
        actor="system",
        target=meta["target"],
        command=meta["message"],
        decision="expired",
        detail={
            "decision_id": decision_id,
            "call_id": call_id,
            "tool_name": meta["tool_name"],
            "risk": meta["risk"],
            "risk_source": meta["risk_source"],
            "scope": meta["scope"],
            "impact": meta["impact"],
            "requested_at": meta["requested_at"],
            "expires_at": meta["expires_at"],
            "audit_recorded": True,
        },
    )
    if history_saved and entry_hash:
        try:
            await db.mark_approval_audited(decision_id, entry_hash)
        except Exception as exc:  # noqa: BLE001 — 下次历史查询会按 decision_id 补偿
            log.warning("approval.expiry_mark_failed", call_id=call_id, exc=str(exc)[:200])
    if not entry_hash:
        log.warning(
            "approval.expiry_audit_failed",
            call_id=call_id,
            tool_name=meta["tool_name"],
            session_id=meta["session_id"],
        )


async def record_auto_decision(
    *,
    session_id: str,
    tool_name: str,
    message: str,
    approved: bool,
    comment: str = "",
    risk: str = "",
    risk_source: str = "",
    target: str = "",
    scope: str = "",
    impact: str = "",
) -> None:
    """把 audit_agent 的自动裁决落审批历史 + 哈希链审计，使其在审批模块可追溯。

    actor="audit_agent"；decision=approved/rejected；裁决理由 comment 并入 impact 便于前端展示。
    与 _record_expired_approval 同款持久化路径。fail-safe：记录失败只告警，绝不影响工具执行。
    """
    decision = "approved" if approved else "rejected"
    decision_id = uuid.uuid4().hex
    call_id = uuid.uuid4().hex[:12]
    now = datetime.now(UTC).isoformat()
    reason = (impact or "").strip()
    if comment:
        reason = f"{reason}（审计：{comment}）" if reason else f"审计：{comment}"
    history_saved = False
    try:
        await db.save_approval_history(
            decision_id=decision_id,
            call_id=call_id,
            tool_name=tool_name,
            session_id=session_id,
            actor="audit_agent",
            decision=decision,
            risk=risk,
            risk_source=risk_source,
            target=target,
            scope=scope,
            impact=reason,
            message=message,
            requested_at=now,
            expires_at=now,
        )
        history_saved = True
    except Exception as exc:  # noqa: BLE001 — 记录失败不影响工具执行
        log.warning("approval.auto_history_failed", tool_name=tool_name, exc=str(exc)[:200])

    entry_hash = await append_audit(
        "tool_approval",
        session_id=session_id,
        actor="audit_agent",
        target=target,
        command=message,
        decision=decision,
        detail={
            "decision_id": decision_id,
            "call_id": call_id,
            "tool_name": tool_name,
            "risk": risk,
            "risk_source": risk_source,
            "scope": scope,
            "impact": reason,
            "comment": comment,
            "reviewer": "audit_agent",
            "requested_at": now,
            "expires_at": now,
            "audit_recorded": True,
        },
    )
    if history_saved and entry_hash:
        try:
            await db.mark_approval_audited(decision_id, entry_hash)
        except Exception as exc:  # noqa: BLE001 — 下次历史查询按 decision_id 补偿
            log.warning("approval.auto_mark_failed", tool_name=tool_name, exc=str(exc)[:200])


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
    然后 await 一个 Future，直到持久决策端点完成该审批或超时。

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
        # shield 防止 wait_for 超时直接取消 Future；若 REST 已认领该请求，给持久化一次短暂宽限。
        return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
    except TimeoutError:
        if fut.done() and not fut.cancelled():
            return fut.result()
        if call_id in _claimed:
            try:
                return await asyncio.wait_for(asyncio.shield(fut), timeout=5.0)
            except TimeoutError:
                if fut.done() and not fut.cancelled():
                    return fut.result()
        log.warning("approval.timeout", call_id=call_id, tool_name=tool_name, session_id=session_id)
        # 超时项不能随内存队列清理而消失：写入同一哈希链，供审批历史长期追溯。
        # 审计层维持 fail-open；工具执行仍在本函数中 fail-closed。
        expired_meta = {
            **_pending_meta[call_id],
            "tool_name": tool_name,
            "message": message,
            "session_id": session_id,
            "risk": risk,
            "risk_source": risk_source,
            "target": target,
            "scope": scope,
            "impact": impact,
        }
        await _record_expired_approval(call_id, expired_meta)
        return False
    except Exception as exc:  # noqa: BLE001 — fail-closed：任何异常都视为拒绝
        log.warning("approval.error", call_id=call_id, tool_name=tool_name, error=str(exc)[:200])
        return False
    finally:
        _pending.pop(call_id, None)
        _pending_meta.pop(call_id, None)
        _claimed.discard(call_id)


def claim_approval(call_id: str, approved: bool) -> dict | None:
    """原子认领一个挂起请求，但暂不唤醒工具；供路由先持久化决策。"""
    fut = _pending.get(call_id)
    if fut is None or fut.done() or call_id in _claimed:
        return None
    _claimed.add(call_id)
    meta = dict(_pending_meta.get(call_id, {}))
    meta["decision"] = "approved" if approved else "rejected"
    return meta


def complete_approval(call_id: str, approved: bool) -> bool:
    """持久化成功后唤醒等待中的工具。"""
    fut = _pending.get(call_id)
    if call_id not in _claimed or fut is None or fut.done():
        _claimed.discard(call_id)
        return False
    fut.set_result(approved)
    _claimed.discard(call_id)
    return True


def release_approval_claim(call_id: str) -> None:
    """持久化失败时释放认领，允许用户重试；工具继续等待并保持 fail-closed。"""
    _claimed.discard(call_id)
