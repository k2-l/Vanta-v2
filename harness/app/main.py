"""FastAPI app 工厂 + 启动入口。"""

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from harness import __version__
from harness.app import auth as auth_module
from harness.app.schemas import HealthResponse
from harness.infra import db
from harness.infra.logging import configure_logging
from harness.infra.profile import ensure_profile
from harness.infra.settings import get_settings

# ── 新路由层 ──────────────────────────────────────────────────────────
from harness.routes import (
    agents,
    board,
    budget,
    chat,
    config,
    containers,
    knowledge,
    mcp,
    memories,
    sessions,
    skills,
    ws,
)


def ensure_workspace() -> Path:
    """给文件工具和实体 provider 准备同一个实际存在的工作目录。"""
    workspace = Path(get_settings().workspace_dir)
    for directory in (workspace, workspace / "agents", workspace / "skills"):
        directory.mkdir(parents=True, exist_ok=True)
    return workspace


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await db.init_db()
    ensure_profile()
    from harness.infra.logging import log
    from harness.tools.mcp import init_mcp_tools, shutdown_mcp

    try:
        workspace = await asyncio.to_thread(ensure_workspace)
        log.info("workspace.ready", root=str(workspace))
    except OSError as exc:
        log.warning("workspace.unavailable", error=str(exc)[:200])

    # ②′ 务实版崩溃续跑：把上次崩在半路的轮（末条是 user 的会话）标记为已中断。fail-open。
    try:
        _interrupted = await db.mark_interrupted_turns()
        if _interrupted:
            log.info("startup.marked_interrupted", count=_interrupted)
    except Exception as exc:  # noqa: BLE001
        log.warning("mark_interrupted_turns.failed", error=str(exc)[:200])

    # ── checkpoint 崩溃续跑地基：durable AsyncPostgresSaver（连接池，并发安全）──
    # fail-open：初始化失败只 warning、不阻断启动，图退回无 checkpointer 版（行为同现状）。
    ckpt_pool = None
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        from harness.core.graph import build

        pg_uri = get_settings().database_url.replace("+asyncpg", "")  # psycopg 用 postgresql://
        ckpt_pool = AsyncConnectionPool(
            conninfo=pg_uri,
            min_size=2,
            max_size=8,
            # 连接 kwargs 照 AsyncPostgresSaver.from_conn_string 源码要求配置
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            open=False,
        )
        await ckpt_pool.open()
        saver = AsyncPostgresSaver(ckpt_pool)
        await saver.setup()  # 幂等建 checkpoint 相关表
        build.set_checkpointer(saver)
        log.info("checkpointer.ready")
    except Exception as exc:  # noqa: BLE001
        log.warning("checkpointer.init_failed", error=str(exc)[:200])
        if ckpt_pool is not None:
            await ckpt_pool.close()
            ckpt_pool = None

    # ── 工具来源统一挂载：builtin（须最先，其后来源归属才正确）→ mcp → plugins ──
    try:
        from harness.tools.source import coordinator
        from harness.tools.sources.builtin import BuiltinSource

        await coordinator.mount(BuiltinSource())
    except Exception as exc:  # noqa: BLE001
        log.warning("builtin.mount_failed", error=str(exc)[:200])
    try:
        await init_mcp_tools()
    except Exception as exc:  # noqa: BLE001
        log.warning("mcp.init_failed", error=str(exc)[:200])
    try:
        from harness.tools.sources.plugin import load_plugins

        await load_plugins()
    except Exception as exc:  # noqa: BLE001
        log.warning("plugins.load_failed", error=str(exc)[:200])
    try:
        yield
    finally:
        await shutdown_mcp()
        if ckpt_pool is not None:
            await ckpt_pool.close()


# SSE/WS 路径豁免：流式请求本身就会超过 30s，不计为慢请求
_STREAMING_PREFIXES = ("/chat", "/ws/")


class _SlowRequestMiddleware(BaseHTTPMiddleware):
    """超过 slow_request_threshold_sec 秒的非流式请求自动记录 warning 日志。"""

    async def dispatch(self, request: Request, call_next):
        from harness.infra.logging import log
        path = request.url.path
        if any(path.startswith(p) for p in _STREAMING_PREFIXES):
            return await call_next(request)
        threshold = get_settings().slow_request_threshold_sec
        t0 = time.monotonic()
        resp = await call_next(request)
        elapsed = time.monotonic() - t0
        if elapsed >= threshold:
            log.warning(
                "slow_request",
                method=request.method,
                path=path,
                elapsed_sec=round(elapsed, 2),
            )
        return resp


def _write_profile(content: str) -> None:
    path = Path(get_settings().profile_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="Harness", version=__version__, lifespan=lifespan)

    app.add_middleware(_SlowRequestMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__, worker_model=get_settings().model_mid)

    @app.get("/metrics")
    async def metrics(_: Annotated[dict, Depends(auth_module.require_auth)]) -> dict:
        """返回进程级运行指标（LLM 调用数、工具调用、缓存命中、injection 检测等）。

        需要 Bearer token 鉴权，防止泄露系统行为指标。
        """
        from harness.infra.metrics import snapshot
        return snapshot()

    # Profile 读写接口
    @app.get("/profile")
    async def get_profile(_: Annotated[dict, Depends(auth_module.require_auth)]) -> dict:
        """返回当前用户 profile 文本内容。"""
        from harness.infra.profile import load_profile
        return {"content": await asyncio.to_thread(load_profile)}

    @app.put("/profile")
    async def put_profile(
        body: dict,
        _: Annotated[dict, Depends(auth_module.require_auth)],
    ) -> dict:
        """更新用户 profile（写入 data/profile.md）。"""
        content = body.get("content", "")
        await asyncio.to_thread(_write_profile, content)
        return {"content": content}

    # 认证
    app.include_router(auth_module.router, tags=["auth"])

    # 核心路由
    app.include_router(chat.router)
    app.include_router(config.router)
    app.include_router(sessions.router)
    app.include_router(memories.router)
    app.include_router(budget.router)

    # 套件路由（skills / agents / knowledge / containers / workspace 同步）
    app.include_router(skills.router)
    app.include_router(agents.router)
    app.include_router(knowledge.router)
    app.include_router(containers.router)

    # 结果看板只读查询（BLACKBOARD P1；操作者视角跨 engagement，secret 不回明文）
    app.include_router(board.router)

    # MCP server 可视化管理（读写都在 harness，见 harness/routes/mcp.py 模块docstring）
    app.include_router(mcp.router)

    # WebSocket 实时推送
    app.include_router(ws.router)

    return app


app = create_app()


def run() -> None:
    """`harness-api` 命令入口。"""
    import uvicorn

    settings = get_settings()
    # 证书+私钥都配置才启用 HTTPS；开发期未配置时使用 HTTP。
    ssl_kwargs: dict[str, str] = {}
    if settings.ssl_certfile and settings.ssl_keyfile:
        ssl_kwargs = {
            "ssl_certfile": settings.ssl_certfile,
            "ssl_keyfile": settings.ssl_keyfile,
        }
    uvicorn.run(
        "harness.app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        access_log=False,
        **ssl_kwargs,
    )


if __name__ == "__main__":
    run()
