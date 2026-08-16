"""API 入参/出参 Pydantic 模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None  # 缺省 → 自动新建
    execution_env: str | None = None  # "local" | "container:<record-id>"


class HealthResponse(BaseModel):
    status: str
    version: str
    worker_model: str = ""


class SessionOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class SessionCreate(BaseModel):
    title: str = "新会话"


class SessionUpdate(BaseModel):
    title: str


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
