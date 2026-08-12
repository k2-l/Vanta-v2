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
