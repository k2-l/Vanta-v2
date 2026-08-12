"""structlog 配置。"""

import logging
import sys

import structlog

# 生产模式（非 DEBUG）下需要抑制到 WARNING 的第三方库 logger
_NOISY_LOGGERS = [
    "httpx",
    "sqlalchemy.engine",
    "qdrant_client",
    "langgraph",
    "langchain",
    "anthropic",
    "uvicorn.access",
]


def configure_logging(level: str = "INFO") -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
    )
    # basicConfig 在 root 已有 handler 时不会设置 level，显式补充
    logging.root.setLevel(numeric_level)

    # 非 DEBUG 模式：抑制第三方库噪音日志，避免塞满日志文件
    if numeric_level > logging.DEBUG:
        for name in _NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)
    else:
        # DEBUG 模式：清除抑制，让第三方库跟随 root logger
        for name in _NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.NOTSET)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger()
