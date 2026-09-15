"""PostgreSQL 持久化 — SQLAlchemy 2.x async + asyncpg。

表：
  sessions   会话元数据
  messages   逐条消息（user/assistant）
  skills     技能注册表
  agents     Agent 注册表
  knowledge  知识库
  containers 容器定义（原 nexus-svc，P2 收回 harness）
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    case,
    func,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from harness.infra.settings import get_settings


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


# ─── 会话 & 消息 ──────────────────────────────────────────────────────

class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="新会话")
    rolling_summary: Mapped[str] = mapped_column(Text, default="")
    # 压缩检查点：此时间点之前的消息已被压进 rolling_summary，runtime 从此点之后取原文喂模型。
    # NULL = 从未主动压缩（历史装载走原有「最近 N 条」逻辑）。原文一律保留，可回退。
    compacted_upto: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    active_engagement_id: Mapped[str] = mapped_column(String(32), default="")  # 当前会话激活的 engagement（scope 门）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    messages: Mapped[list[Message]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    session: Mapped[Session] = relationship(back_populates="messages")


# ─── 套件注册表 ───────────────────────────────────────────────────────

class TokenUsage(Base):
    """每次 LLM 调用的 token 消耗记录，用于预算统计。"""
    __tablename__ = "token_usage"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    date: Mapped[object] = mapped_column(Date, index=True)        # 按日汇总
    model: Mapped[str] = mapped_column(String(100), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KnowledgeRecord(Base):
    __tablename__ = "knowledge"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    category: Mapped[str] = mapped_column(String(200), default="", index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="[]")


class ContainerRecord(Base):
    """容器定义 —— 原 nexus-svc 管理，P2 收回 harness（podman 直连）。

    表由 nexus 用原始 SQL 建过（列名/类型见此）；harness 接管后 create_all 对已存在的表
    跳过，仅在全新库（P4 删 nexus 后）按本模型建表。
    """
    __tablename__ = "containers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    image: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="created")   # created|running|stopped
    ports: Mapped[str] = mapped_column(Text, default="[]")              # JSON list[str]："8080:80"
    env_vars: Mapped[str] = mapped_column(Text, default="[]")           # JSON list[str]："K=V"
    container_id: Mapped[str] = mapped_column(Text, default="")         # podman 容器 ID（未创建则空）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class ScriptRecord(Base):
    """L3 脚本 — 可被 skill/agent 依赖的自动化脚本。"""
    __tablename__ = "scripts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(50), default="")               # python | bash | sql | generic
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TemplateRecord(Base):
    """L3 模版 — 可被 skill/agent 依赖的输出模板。"""
    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="")              # report | finding | config
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class SessionPhase(Base):
    __tablename__ = "session_phases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class SessionRunEvent(Base):
    """运行遥测历史；不保存正文 delta，只保留工具、日志、Worker 与用量事件。"""

    __tablename__ = "session_run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)



class EngagementRecord(Base):
    """授权 engagement —— scope 授权边界的持久化。

    scope_targets / authorization_ref / 有效期是一切主动动作的前置门；扫描·渗透前
    校验 target_in_scope() + is_engagement_active()（见 harness/infra/engagement.py）。
    """

    __tablename__ = "engagements"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    scope_targets: Mapped[list | None] = mapped_column(JSON, nullable=True)        # list[str]
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)   # draft|active|ended
    authorization_ref: Mapped[str] = mapped_column(Text, default="")              # 授权凭证引用（激活前置硬门）
    dns_resolver_ip: Mapped[str] = mapped_column(String(64), default="")          # 可选受控 DNS resolver
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class AuditLedgerRecord(Base):
    """append-only 审计账本 —— 法律可辩的动作留痕，只增不改不删。

    每个主动动作 / 审批 / scope 判定落一行；prev_hash + entry_hash 构成哈希链，
    改任一历史行会使其后所有 entry_hash 对不上（防篡改，见 harness/infra/audit_ledger.py）。
    """

    __tablename__ = "audit_ledger"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    engagement_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    session_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    actor: Mapped[str] = mapped_column(String(64), default="agent")               # agent | human | system
    action: Mapped[str] = mapped_column(String(64), index=True)                   # scan|approval|scope_check|webfetch|teardown
    target: Mapped[str] = mapped_column(Text, default="")
    command: Mapped[str] = mapped_column(Text, default="")
    decision: Mapped[str] = mapped_column(String(32), default="")                 # allow|deny|ask|approved|rejected|blocked
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    entry_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class SecurityFinding(Base):
    """安全发现 —— 审计 / 扫描 / 渗透产出的结构化发现，归属 engagement，供报告。"""

    __tablename__ = "security_findings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    engagement_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(500))
    severity: Mapped[str] = mapped_column(String(16), default="info", index=True)  # critical|high|medium|low|info
    category: Mapped[str] = mapped_column(String(100), default="")                 # CWE-89 / OWASP-A03 等
    target: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    remediation: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)    # open|triaged|false_positive|fixed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    # ── 看板泛化（BLACKBOARD P1）：finding 是 artifact 的一个 kind；evidence 即通用正文 ──
    producer: Mapped[str] = mapped_column(String(200), default="")                       # 产出方 agent/session
    kind: Mapped[str] = mapped_column(String(32), default="finding", index=True)         # finding|scan_result|recon|report|note|secret_ref
    sensitivity: Mapped[str] = mapped_column(String(16), default="internal", index=True) # public|internal|secret
    tags: Mapped[str] = mapped_column(Text, default="[]")                                # JSON list
    vault_ref: Mapped[str] = mapped_column(String(200), default="")                      # secret:// 引用（P3）
    share_with: Mapped[str] = mapped_column(Text, default="[]")                          # JSON list 白名单（P2/P3）
    dedup_key: Mapped[str] = mapped_column(String(200), default="", index=True)


# SecurityFinding 即"看板 artifact"的实体表（kind=finding 是其一个特例）；BLACKBOARD 用别名引用。
Artifact = SecurityFinding


# ─── 引擎 & 工厂 ──────────────────────────────────────────────────────

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _ensure_engine():
    global _engine, _sessionmaker
    if _engine is not None:
        return
    s = get_settings()
    _engine = create_async_engine(
        s.database_url,
        echo=False,
        future=True,
        pool_size=5,
        max_overflow=10,
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)


async def init_db() -> None:
    _ensure_engine()
    assert _engine is not None
    # create_all 单独一个事务：PostgreSQL 里一旦某条语句失败，整个事务进入 aborted 态，
    # commit 时会整体回滚。若把 create_all 和下面的 ALTER 放同一事务，某条 ALTER（列已存在）
    # 失败就会把刚建的新表一起回滚掉（hk 部署「新表建不出来」的坑）。故分开。
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # 兼容已有数据库：新列不会被 create_all 自动添加，用 ALTER TABLE 兜底。
    # 每条单独事务，失败（列已存在）只回滚自己，不影响上面的建表。
    for col_sql in [
        "ALTER TABLE agents ADD COLUMN enable_critic BOOLEAN DEFAULT FALSE",
        "ALTER TABLE sessions ADD COLUMN active_engagement_id VARCHAR(32) DEFAULT ''",
        "ALTER TABLE sessions ADD COLUMN compacted_upto TIMESTAMPTZ",
        # 看板泛化（BLACKBOARD P1）：给 security_findings 补 artifact 通用列
        "ALTER TABLE security_findings ADD COLUMN producer VARCHAR(200) DEFAULT ''",
        "ALTER TABLE security_findings ADD COLUMN kind VARCHAR(32) DEFAULT 'finding'",
        "ALTER TABLE security_findings ADD COLUMN sensitivity VARCHAR(16) DEFAULT 'internal'",
        "ALTER TABLE security_findings ADD COLUMN tags TEXT DEFAULT '[]'",
        "ALTER TABLE security_findings ADD COLUMN vault_ref VARCHAR(200) DEFAULT ''",
        "ALTER TABLE security_findings ADD COLUMN share_with TEXT DEFAULT '[]'",
        "ALTER TABLE security_findings ADD COLUMN dedup_key VARCHAR(200) DEFAULT ''",
    ]:
        try:
            async with _engine.begin() as conn:
                await conn.execute(text(col_sql))
        except Exception:
            pass  # 列已存在


def session_factory() -> async_sessionmaker[AsyncSession]:
    _ensure_engine()
    assert _sessionmaker is not None
    return _sessionmaker


@asynccontextmanager
async def transaction(
    db_session: AsyncSession | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession that commits on exit and rolls back on error.

    Usage::

        async with transaction() as db:
            db.add(some_record)
            # commit happens automatically on clean exit

    An existing session can be passed in (e.g. when you want to share one
    session across several helpers without nesting transactions)::

        async with transaction(existing_db) as db:
            ...  # uses existing_db; caller is responsible for the outer commit
    """
    if db_session is not None:
        # Reuse the caller-supplied session; don't commit/rollback here.
        yield db_session
        return

    sf = session_factory()
    async with sf() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise


# ─── 业务封装 ─────────────────────────────────────────────────────────

def new_id() -> str:
    return uuid.uuid4().hex[:12]


async def create_session(title: str = "新会话") -> Session:
    sf = session_factory()
    async with sf() as db:
        sess = Session(id=new_id(), title=title)
        db.add(sess)
        await db.commit()
        await db.refresh(sess)
        return sess


async def list_sessions(limit: int = 50) -> list[Session]:
    sf = session_factory()
    async with sf() as db:
        result = await db.execute(
            select(Session).order_by(Session.updated_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


async def list_run_summaries(limit: int = 60) -> list[dict]:
    """一次查询返回运行中心所需字段，避免客户端逐会话读取 phases。"""

    steps = func.count(SessionPhase.id)
    active = func.sum(
        case((SessionPhase.status.in_(("pending", "running")), 1), else_=0)
    )
    failed = func.sum(case((SessionPhase.status == "failed", 1), else_=0))
    started_at = func.min(SessionPhase.created_at)
    phase_updated_at = func.max(SessionPhase.updated_at)
    sf = session_factory()
    async with sf() as db:
        result = await db.execute(
            select(
                Session.id,
                Session.title,
                Session.created_at,
                Session.updated_at,
                steps.label("steps"),
                active.label("active"),
                failed.label("failed"),
                started_at.label("started_at"),
                phase_updated_at.label("phase_updated_at"),
            )
            .outerjoin(SessionPhase, SessionPhase.session_id == Session.id)
            .group_by(
                Session.id,
                Session.title,
                Session.created_at,
                Session.updated_at,
            )
            .order_by(Session.updated_at.desc())
            .limit(limit)
        )

    summaries: list[dict] = []
    for row in result:
        step_count = int(row.steps or 0)
        status = (
            "queued"
            if step_count == 0
            else "running"
            if int(row.active or 0) > 0
            else "failed"
            if int(row.failed or 0) > 0
            else "completed"
        )
        finished_at = row.phase_updated_at if status in ("completed", "failed", "cancelled") else None
        duration_end = finished_at or (_now() if row.started_at else None)
        duration_ms = (
            max(0, int((duration_end - row.started_at).total_seconds() * 1000))
            if duration_end and row.started_at
            else None
        )
        summaries.append(
            {
                "id": row.id,
                "title": row.title,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "status": status,
                "steps": step_count,
                "started_at": row.started_at,
                "finished_at": finished_at,
                "duration_ms": duration_ms,
            }
        )
    return summaries


async def get_session(session_id: str) -> Session | None:
    sf = session_factory()
    async with sf() as db:
        return await db.get(Session, session_id)


async def delete_session(session_id: str) -> bool:
    sf = session_factory()
    async with sf() as db:
        sess = await db.get(Session, session_id)
        if sess is None:
            return False
        await db.delete(sess)
        await db.commit()
        return True


async def append_message(session_id: str, role: str, content: str) -> Message:
    sf = session_factory()
    async with sf() as db:
        msg = Message(id=new_id(), session_id=session_id, role=role, content=content)
        db.add(msg)
        # 直接 UPDATE 代替 SELECT * + ORM 赋值，省一次全行读取
        await db.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(updated_at=_now())
        )
        await db.commit()
        await db.refresh(msg)
        return msg


async def recent_messages(session_id: str, n: int = 16) -> list[Message]:
    sf = session_factory()
    async with sf() as db:
        result = await db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(n)
        )
        rows = list(result.scalars().all())
        rows.reverse()
        return rows


async def update_title(session_id: str, title: str) -> bool:
    sf = session_factory()
    async with sf() as db:
        result = await db.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(title=title[:200])
        )
        await db.commit()
        return result.rowcount > 0


_INTERRUPTED_NOTICE = "⚠️ 上一条回复因服务重启而中断，请重新发送。"


async def mark_interrupted_turns() -> int:
    """启动时把「崩在半路」的轮标记为已中断（务实版崩溃续跑 ②′）。

    判据：某会话最新一条消息 role='user'（assistant 回复未落库）。启动时无活跃轮，
    故这类会话即上次进程崩溃 / 重启时正在跑的轮。给它追加一条 assistant 说明消息，
    使中断在历史里可见、不留诡异半截状态。幂等：标记后末条变 assistant，下次不再命中。

    注：终止错误（无 assistant 落库）的轮也会留悬空 user、被一并标记——不精确但
    「未完成、请重发」不算错。
    """
    sf = session_factory()
    async with sf() as db:
        rn = (
            func.row_number()
            .over(partition_by=Message.session_id, order_by=Message.created_at.desc())
            .label("rn")
        )
        ranked = select(Message.session_id, Message.role, rn).subquery()
        stmt = select(ranked.c.session_id).where(
            (ranked.c.rn == 1) & (ranked.c.role == "user")
        )
        session_ids = list((await db.execute(stmt)).scalars().all())
        for sid in session_ids:
            db.add(
                Message(
                    id=new_id(),
                    session_id=sid,
                    role="assistant",
                    content=_INTERRUPTED_NOTICE,
                )
            )
        if session_ids:
            await db.commit()
    return len(session_ids)


# ─── 交叉引用索引 ─────────────────────────────────────────────────────


async def get_rolling_summary(session_id: str) -> str:
    """读取会话的 rolling_summary（跨轮摘要）。只 SELECT 目标列，不加载全行。"""
    sf = session_factory()
    async with sf() as db:
        result = await db.execute(
            select(Session.rolling_summary).where(Session.id == session_id)
        )
        val = result.scalar()
        return val or ""


async def update_rolling_summary(session_id: str, summary: str) -> None:
    """写回 rolling_summary 到 sessions 表。直接 UPDATE 省去全行 SELECT。"""
    sf = session_factory()
    async with sf() as db:
        await db.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(rolling_summary=summary)
        )
        await db.commit()


# ─── 主动压缩（压缩检查点）─────────────────────────────────────────────


async def get_compaction(session_id: str) -> tuple[str, datetime | None]:
    """读取会话的 (rolling_summary, compacted_upto)。一次 SELECT 取两列。"""
    sf = session_factory()
    async with sf() as db:
        result = await db.execute(
            select(Session.rolling_summary, Session.compacted_upto).where(
                Session.id == session_id
            )
        )
        row = result.one_or_none()
        if row is None:
            return "", None
        return (row[0] or ""), row[1]


async def set_compaction(session_id: str, summary: str, upto: datetime) -> None:
    """用户主动压缩落库：同时写 rolling_summary + compacted_upto（检查点）。

    只动这两列、不触碰 messages（原文全保留），故与正在运行的轮无数据竞争：
    最坏只影响下一轮的上下文装载。
    """
    sf = session_factory()
    async with sf() as db:
        await db.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(rolling_summary=summary, compacted_upto=upto)
        )
        await db.commit()


async def messages_upto(session_id: str, upto: datetime | None = None) -> list[Message]:
    """取「压缩源」原文：created_at <= upto 的消息按时间正序；upto=None 取全部。

    供主动压缩预览时把检查点之前的原文喂给压缩器（服务层再按 token 上限截断）。
    """
    sf = session_factory()
    async with sf() as db:
        stmt = select(Message).where(Message.session_id == session_id)
        if upto is not None:
            stmt = stmt.where(Message.created_at <= upto)
        stmt = stmt.order_by(Message.created_at.asc())
        result = await db.execute(stmt)
        return list(result.scalars().all())


async def messages_after_checkpoint(session_id: str, fallback_n: int = 16) -> list[Message]:
    """runtime 装历史用：有压缩检查点则取其之后的原文（正序）；无则回退「最近 fallback_n 条」。

    NULL 检查点（存量会话/从未压缩）行为与原 recent_messages 完全一致。
    """
    summary_upto = None
    sf = session_factory()
    async with sf() as db:
        cp = await db.execute(select(Session.compacted_upto).where(Session.id == session_id))
        summary_upto = cp.scalar()
        if summary_upto is None:
            # 回退：最近 fallback_n 条（复用 recent_messages 语义，避免重复 SQL）
            result = await db.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at.desc())
                .limit(fallback_n)
            )
            rows = list(result.scalars().all())
            rows.reverse()
            return rows
        result = await db.execute(
            select(Message)
            .where(Message.session_id == session_id, Message.created_at > summary_upto)
            .order_by(Message.created_at.asc())
        )
        return list(result.scalars().all())


async def uncompacted_history_gap(session_id: str, fallback_n: int = 16) -> int:
    """返回未被摘要覆盖且落在 fallback 窗口之外的消息数。"""
    sf = session_factory()
    async with sf() as db:
        result = await db.execute(
            select(Session.compacted_upto, func.count(Message.id))
            .outerjoin(Message, Message.session_id == Session.id)
            .where(Session.id == session_id)
            .group_by(Session.compacted_upto)
        )
        row = result.one_or_none()
    if row is None or row[0] is not None:
        return 0
    return max(0, int(row[1]) - max(0, fallback_n))


async def upsert_phase(phase_id: str, session_id: str, payload: dict) -> None:
    # 存储主键用 per-(session_id, phase_id) 的 md5（固定 32 hex 字符，正好 String(32)）。
    # 原因：phase_id 跨会话复用裸常量（主阶段恒为 "agent"），若直接作单列 PK，首个会话
    # 占住后其余会话的 upsert 会命中并改写它那一行（且不改 session_id）→ list_phases(其它
    # 会话) 恒空。用复合 hash 做主键保证每会话独立行。对外 id/parent_id 仍是原始值（payload
    # 固化原始 id + routes/sessions.py 序列化还原），故不改 schema、不变更 GET /phases 契约。
    pk = hashlib.md5(f"{session_id}:{phase_id}".encode()).hexdigest()
    payload = {**payload, "id": phase_id}
    sf = session_factory()
    async with sf() as db:
        existing = await db.get(SessionPhase, pk)
        if existing is None:
            record = SessionPhase(
                id=pk,
                session_id=session_id,
                parent_id=payload.get("parent_id") or None,
                type=payload.get("type", "phase"),
                status=payload.get("status", "running"),
                label=payload.get("label") or None,
                payload=payload,
            )
            db.add(record)
        else:
            existing.status = payload.get("status", existing.status)
            existing.label = payload.get("label") or existing.label
            existing.payload = payload
            existing.updated_at = _now()
        await db.commit()


async def list_phases(session_id: str) -> list[SessionPhase]:
    sf = session_factory()
    async with sf() as db:
        result = await db.execute(
            select(SessionPhase)
            .where(SessionPhase.session_id == session_id)
            .order_by(SessionPhase.created_at)
        )
        return list(result.scalars().all())


async def append_run_event(session_id: str, event: str, data: dict) -> SessionRunEvent:
    sf = session_factory()
    async with sf() as db:
        record = SessionRunEvent(session_id=session_id, event=event, data=data)
        db.add(record)
        await db.execute(
            update(Session).where(Session.id == session_id).values(updated_at=_now())
        )
        await db.commit()
        await db.refresh(record)
        return record


async def list_run_events(
    session_id: str,
    *,
    after_seq: int = 0,
    limit: int = 1000,
) -> list[SessionRunEvent]:
    sf = session_factory()
    async with sf() as db:
        result = await db.execute(
            select(SessionRunEvent)
            .where(
                SessionRunEvent.session_id == session_id,
                SessionRunEvent.id > after_seq,
            )
            .order_by(SessionRunEvent.id)
            .limit(limit)
        )
        return list(result.scalars().all())

# ─── Engagement（授权范围）CRUD ─────────────────────────────────────────

async def create_engagement(
    name: str,
    scope_targets: list[str],
    *,
    authorization_ref: str = "",
    dns_resolver_ip: str = "",
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> EngagementRecord:
    sf = session_factory()
    async with sf() as db:
        rec = EngagementRecord(
            id=new_id(),
            name=name[:200],
            scope_targets=list(scope_targets or []),
            authorization_ref=authorization_ref,
            dns_resolver_ip=dns_resolver_ip,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        db.add(rec)
        await db.commit()
        await db.refresh(rec)
        return rec


async def get_engagement(engagement_id: str) -> EngagementRecord | None:
    sf = session_factory()
    async with sf() as db:
        return await db.get(EngagementRecord, engagement_id)


async def list_engagements(limit: int = 50) -> list[EngagementRecord]:
    sf = session_factory()
    async with sf() as db:
        result = await db.execute(
            select(EngagementRecord).order_by(EngagementRecord.updated_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


async def set_engagement_status(engagement_id: str, status: str) -> bool:
    sf = session_factory()
    async with sf() as db:
        result = await db.execute(
            update(EngagementRecord)
            .where(EngagementRecord.id == engagement_id)
            .values(status=status, updated_at=_now())
        )
        await db.commit()
        return result.rowcount > 0


async def set_active_engagement(session_id: str, engagement_id: str) -> bool:
    """把某 engagement 设为会话的活跃 engagement（scope 门来源）。engagement_id 空串=清除。"""
    sf = session_factory()
    async with sf() as db:
        result = await db.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(active_engagement_id=engagement_id)
        )
        await db.commit()
        return result.rowcount > 0


async def get_active_engagement_id(session_id: str) -> str:
    """读会话当前激活的 engagement_id；无则空串。"""
    sf = session_factory()
    async with sf() as db:
        result = await db.execute(
            select(Session.active_engagement_id).where(Session.id == session_id)
        )
        return result.scalar() or ""


# ─── 安全发现（findings）──────────────────────────────────────────────

async def create_finding(
    *,
    engagement_id: str | None,
    title: str,
    severity: str = "info",
    category: str = "",
    target: str = "",
    evidence: str = "",
    remediation: str = "",
) -> SecurityFinding:
    sf = session_factory()
    async with sf() as db:
        rec = SecurityFinding(
            id=new_id(),
            engagement_id=engagement_id,
            title=title[:500],
            severity=severity,
            category=category[:100],
            target=target,
            evidence=evidence,
            remediation=remediation,
        )
        db.add(rec)
        await db.commit()
        await db.refresh(rec)
        return rec


async def list_findings(
    engagement_id: str | None = None, status: str = ""
) -> list[SecurityFinding]:
    sf = session_factory()
    async with sf() as db:
        q = select(SecurityFinding)
        if engagement_id is not None:
            q = q.where(SecurityFinding.engagement_id == engagement_id)
        if status:
            q = q.where(SecurityFinding.status == status)
        return list((await db.execute(q.limit(500))).scalars().all())


async def create_artifact(
    *,
    engagement_id: str | None,
    kind: str,
    title: str,
    content: str = "",
    producer: str = "",
    sensitivity: str = "internal",
    tags: list[str] | None = None,
    vault_ref: str = "",
    share_with: list[str] | None = None,
    dedup_key: str = "",
) -> SecurityFinding:
    """写一条看板 artifact（BLACKBOARD P1）。content 落 evidence 列（甲：evidence 即通用正文）。"""
    sf = session_factory()
    async with sf() as db:
        rec = SecurityFinding(
            id=new_id(),
            engagement_id=engagement_id,
            kind=kind,
            title=title[:500],
            evidence=content,
            producer=producer[:200],
            sensitivity=sensitivity,
            tags=json.dumps(tags or []),
            vault_ref=vault_ref[:200],
            share_with=json.dumps(share_with or []),
            dedup_key=dedup_key[:200],
        )
        db.add(rec)
        await db.commit()
        await db.refresh(rec)
        return rec


async def list_artifacts(
    engagement_id: str | None = None, kind: str | None = None
) -> list[SecurityFinding]:
    """列当前 engagement 的 artifact（L1 隔离）；可按 kind 过滤，最新在前。"""
    sf = session_factory()
    async with sf() as db:
        q = select(SecurityFinding)
        if engagement_id is not None:
            q = q.where(SecurityFinding.engagement_id == engagement_id)
        if kind:
            q = q.where(SecurityFinding.kind == kind)
        q = q.order_by(SecurityFinding.created_at.desc()).limit(500)
        return list((await db.execute(q)).scalars().all())


async def set_finding_status(finding_id: str, status: str) -> bool:
    sf = session_factory()
    async with sf() as db:
        result = await db.execute(
            update(SecurityFinding)
            .where(SecurityFinding.id == finding_id)
            .values(status=status, updated_at=_now())
        )
        await db.commit()
        return result.rowcount > 0
