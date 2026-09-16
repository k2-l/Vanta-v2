"""API 入参/出参 Pydantic 模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None  # 缺省 → 自动新建
    execution_env: str | None = None  # "local" | "container:<record-id>"


class ServerCapabilities(BaseModel):
    """桌面客户端能力协商；只声明后端当前真正支持的 run 级能力。"""

    api_version: str = "1"
    # GET /sessions/{id}/phases 提供 run（会话执行）的阶段快照。
    run_snapshot: bool = True
    # GET /sessions/{id}/events 提供脱敏后的结构化运行遥测历史。
    run_history: bool = True
    # 后端事件无 sequence，不支持按序重放；断线后由客户端重拉快照对账。
    event_replay: bool = False
    # 无服务端取消端点；对话流由客户端 stream_stop 中断。
    run_cancel: bool = False
    # 后端提供受控 artifact 详情；实际写盘仅由 Rust Core 完成。
    artifact_export: bool = True


class HealthResponse(BaseModel):
    status: str
    version: str
    worker_model: str = ""
    api_version: str = "1"
    capabilities: ServerCapabilities = Field(default_factory=ServerCapabilities)


class SessionOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class RunSummaryOut(BaseModel):
    """桌面运行中心的轻量汇总；当前一个 run 对应一个 session。"""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    status: str
    steps: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None


class RunEventOut(BaseModel):
    """可持久化的运行遥测事件；seq 是单调递增游标。"""

    seq: int
    event: str
    data: dict
    created_at: datetime


class SessionCreate(BaseModel):
    title: str = Field(default="新会话", min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("会话标题不能为空")
        return title


class SessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("会话标题不能为空")
        return title


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime


class CompressPreviewOut(BaseModel):
    """主动压缩「预览」结果（不落库，供用户确认/编辑）。"""

    summary: str  # 生成的结构化摘要（用户可编辑后再提交）
    upto: datetime  # 压缩检查点边界（此刻最后一条消息的时间）；提交时原样回传
    messages: int  # 被压缩的原文消息条数
    tokens_before: int  # 压缩前这些原文的估算 token
    tokens_after: int  # 压缩后摘要的估算 token


class CompressCommitRequest(BaseModel):
    """主动压缩「提交」入参：把（可能编辑过的）摘要 + 检查点写入会话。"""

    summary: str
    upto: datetime


class RememberRequest(BaseModel):
    text: str
    session_id: str | None = None
    role: str = "user"


class RememberResponse(BaseModel):
    id: str


class MemoryItem(BaseModel):
    id: str
    text: str
    metadata: dict = {}
    distance: float | None = None


class MemorySearchRequest(BaseModel):
    query: str
    k: int = 5
