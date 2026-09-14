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


async def request_approval(
    session_id: str,
    tool_name: str,
    message: str,
    *,
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


def resolve_approval(call_id: str, approved: bool) -> bool:
    """REST 决策端点调用：resolve 对应的 Future。

    返回 False 表示 call_id 不存在或已被处理（前端应提示"该审批请求已失效"）。
    """
    fut = _pending.get(call_id)
    if fut is None or fut.done():
        return False
    fut.set_result(approved)
    return True
