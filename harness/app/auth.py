"""单用户 JWT 鉴权 + 登录限流。

设计：
  - 密码：HARNESS_AUTH_PASSWORD（仅环境变量，secrets.compare_digest 常时比较）
  - Token：HS256 JWT，HARNESS_AUTH_SECRET 作为签名密钥
  - 有效期：默认 7 天（auth_token_ttl_hours）
  - 限流：每 IP 每分钟 N 次登录尝试，进程内令牌桶（重启重置）

公开路由：/health  /auth/login
保护路由：其它所有（用 Depends(require_auth) 标注）
"""

from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from harness.infra.logging import log
from harness.infra.settings import get_settings

JWT_ALG = "HS256"

router = APIRouter()


# ---------- Models ----------

class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: datetime


class MeResponse(BaseModel):
    authenticated: bool
    expires_at: datetime | None = None


# ---------- Token ----------

def _ensure_configured() -> None:
    s = get_settings()
    if not s.auth_password:
        raise HTTPException(
            status_code=503,
            detail="服务未配置 HARNESS_AUTH_PASSWORD 环境变量",
        )
    if not s.auth_secret or len(s.auth_secret.encode("utf-8")) < 32:
        raise HTTPException(
            status_code=503,
            detail="HARNESS_AUTH_SECRET 未配置或少于 32 字节",
        )


def _make_token() -> tuple[str, datetime]:
    s = get_settings()
    exp = datetime.now(UTC) + timedelta(hours=s.auth_token_ttl_hours)
    payload = {
        "sub": "owner",
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, s.auth_secret, algorithm=JWT_ALG)
    return token, exp


def _verify_token(token: str) -> dict:
    s = get_settings()
    try:
        return jwt.decode(token, s.auth_secret, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token 已过期，请重新登录") from None
    except jwt.InvalidTokenError:
        raise HTTPException(401, "无效 token") from None


# ---------- 简单 in-memory 限流（按 IP）----------

_RATE_BUCKET: dict[str, deque[float]] = defaultdict(deque)
_RATE_WINDOW_S = 60.0


def _check_rate_limit(ip: str) -> None:
    s = get_settings()
    bucket = _RATE_BUCKET[ip]
    now = time.monotonic()
    # 清理过期
    while bucket and now - bucket[0] > _RATE_WINDOW_S:
        bucket.popleft()
    if len(bucket) >= s.auth_login_rate_limit:
        retry = int(_RATE_WINDOW_S - (now - bucket[0]))
        raise HTTPException(
            status_code=429,
            detail=f"登录尝试过于频繁，请 {retry} 秒后重试",
        )
    bucket.append(now)


# ---------- Dependency ----------

async def require_auth(
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """所有受保护路由通过此 Depends 校验。"""
    _ensure_configured()
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "缺少 Authorization: Bearer <token>")
    token = authorization.split(" ", 1)[1].strip()
    return _verify_token(token)


# ---------- Routes ----------

@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request) -> LoginResponse:
    _ensure_configured()
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip)

    s = get_settings()
    if not secrets.compare_digest(req.password, s.auth_password):
        log.warning("auth.login_failed", ip=ip)
        raise HTTPException(401, "密码错误")

    token, exp = _make_token()
    log.info("auth.login_ok", ip=ip)
    return LoginResponse(token=token, expires_at=exp)


@router.get("/auth/me", response_model=MeResponse)
async def me(claims: Annotated[dict, Depends(require_auth)]) -> MeResponse:
    exp = claims.get("exp")
    return MeResponse(
        authenticated=True,
        expires_at=datetime.fromtimestamp(exp, tz=UTC) if exp else None,
    )
