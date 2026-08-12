"""Agent 事件类型 + SSE 序列化。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class TextDelta(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    role: Literal["worker"] = "worker"
    text: str
    task_id: str = ""


class ToolCall(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    role: Literal["worker"] = "worker"
    tool: str
    inputs: dict[str, Any]
    task_id: str = ""


class ToolResultEvent(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    role: Literal["worker"] = "worker"
    tool: str
    ok: bool
    output: str
    error: str | None = None
    task_id: str = ""


class WorkerStart(BaseModel):
    type: Literal["worker_start"] = "worker_start"
    worker: str
    instruction: str
    task_id: str = ""


class WorkerEnd(BaseModel):
    type: Literal["worker_end"] = "worker_end"
    worker: str
    status: Literal["ok", "failed"]
    summary: str
    task_id: str = ""


class UsageEvent(BaseModel):
    type: Literal["usage"] = "usage"
    model: str
    turn_input: int = 0
    turn_output: int = 0
    turn_cost_usd: float = 0.0
    session_input: int = 0
    session_output: int = 0
    session_cost_usd: float = 0.0


class PhaseEvent(BaseModel):
    """阶段进度事件，驱动 TasksPanel 中的阶段列表。"""

    type: Literal["phase"] = "phase"
    id: str
    label: str = ""
    status: Literal["pending", "running", "ok", "failed"] = "running"
    detail: str = ""
    task_id: str = ""
    parent_id: str = ""


class TaskLogEvent(BaseModel):
    """任务日志行，附加到某个阶段的日志列表中。"""

    type: Literal["task_log"] = "task_log"
    task_id: str = ""
    message: str = ""


class ToolErrorEvent(BaseModel):
    """工具执行失败的结构化错误事件，供前端展示详情和重试提示。"""

    type: Literal["tool_error"] = "tool_error"
    role: Literal["worker"] = "worker"
    tool: str
    error_code: str  # TIMEOUT / PERMISSION_DENIED / RATE_LIMIT / …
    message: str
    retryable: bool = True
    task_id: str = ""


class Done(BaseModel):
    type: Literal["done"] = "done"


Event = (
    TextDelta
    | ToolCall
    | ToolResultEvent
    | ToolErrorEvent
    | WorkerStart
    | WorkerEnd
    | PhaseEvent
    | TaskLogEvent
    | UsageEvent
    | Done
)


def event_to_sse(event: Event) -> dict[str, str]:
    """Event → sse_starlette 期望的 dict 形态。"""
    return {"event": event.type, "data": event.model_dump_json()}
