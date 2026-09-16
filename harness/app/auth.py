"""单用户短期访问令牌 + 可撤销刷新会话 + 登录限流。

设计：
  - 密码：HARNESS_AUTH_PASSWORD（仅环境变量，secrets.compare_digest 常时比较）
  - Token：HS256 JWT，HARNESS_AUTH_SECRET 作为签名密钥；访问令牌默认 1 小时
  - 登录会话 / 刷新令牌由 auth_token_ttl_hours 配置
  - 服务端只持久化刷新令牌 sha256；刷新时轮换，登出后整个会话立即失效
  - 限流：每 IP 每分钟 N 次登录尝试，进程内令牌桶（重启重置）

公开路由：/health  /auth/login  /auth/refresh
保护路由：其它所有（用 Depends(require_auth) 标注）
"""

from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel

from harness.infra import db
from harness.infra.logging import log
from harness.infra.settings import get_settings

JWT_ALG = "HS256"

router = APIRouter()


# ---------- Models ----------

class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str
    refresh_token: str
    expires_at: datetime
    refresh_expires_at: datetime


class RefreshRequest(BaseModel):
    refresh_token: str


class MeResponse(BaseModel):
    authenticated: bool
    expires_at: datetime | None = None
    refresh_expires_at: datetime | None = None


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


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _make_token_pair(
    session_id: str,
    refresh_expires_at: datetime,
) -> tuple[str, str, datetime]:
    s = get_settings()
    now = datetime.now(UTC)
    access_exp = min(
        now + timedelta(minutes=s.auth_access_token_ttl_minutes),
        refresh_expires_at,
    )
    common = {
        "sub": "owner",
        "sid": session_id,
        "iat": int(now.timestamp()),
    }
    access_token = jwt.encode(
        {**common, "type": "access", "jti": secrets.token_hex(16), "exp": int(access_exp.timestamp())},
        s.auth_secret,
        algorithm=JWT_ALG,
    )
    refresh_token = jwt.encode(
        {
            **common,
            "type": "refresh",
            "jti": secrets.token_hex(16),
            "exp": int(refresh_expires_at.timestamp()),
        },
        s.auth_secret,
        algorithm=JWT_ALG,
    )
    return access_token, refresh_token, access_exp


def _decode_token(token: str, expected_type: str) -> dict:
    s = get_settings()
    try:
        claims = jwt.decode(token, s.auth_secret, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token 已过期，请重新登录") from None
    except jwt.InvalidTokenError:
        raise HTTPException(401, "无效 token") from None
    if claims.get("type") != expected_type or not claims.get("sid"):
        raise HTTPException(401, f"无效 {expected_type} token")
    return claims


async def verify_access_token(token: str) -> dict:
    """校验签名、类型和服务端会话状态；登出后访问令牌立即失效。"""
    claims = _decode_token(token, "access")
    record = await db.get_auth_session(str(claims["sid"]))
    now = datetime.now(UTC)
    if record is None or record.revoked_at is not None or record.expires_at <= now:
        raise HTTPException(401, "登录会话已失效，请重新登录")
    return claims


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
    return await verify_access_token(token)


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

    session_id = secrets.token_hex(16)
    refresh_expires_at = datetime.now(UTC) + timedelta(hours=s.auth_token_ttl_hours)
    token, refresh_token, expires_at = _make_token_pair(session_id, refresh_expires_at)
    await db.create_auth_session(session_id, _token_hash(refresh_token), refresh_expires_at)
    log.info("auth.login_ok", ip=ip, session_id=session_id)
    return LoginResponse(
        token=token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        refresh_expires_at=refresh_expires_at,
    )


@router.post("/auth/refresh", response_model=LoginResponse)
async def refresh(req: RefreshRequest) -> LoginResponse:
    """轮换刷新令牌并签发新的短期访问令牌；旧刷新令牌立即作废。"""
    _ensure_configured()
    claims = _decode_token(req.refresh_token, "refresh")
    session_id = str(claims["sid"])
    record = await db.get_auth_session(session_id)
    now = datetime.now(UTC)
    old_hash = _token_hash(req.refresh_token)
    if (
        record is None
        or record.revoked_at is not None
        or record.expires_at <= now
        or not secrets.compare_digest(record.refresh_token_hash, old_hash)
    ):
        raise HTTPException(401, "刷新会话已失效，请重新登录")
    token, refresh_token, expires_at = _make_token_pair(session_id, record.expires_at)
    rotated = await db.rotate_auth_session(session_id, old_hash, _token_hash(refresh_token))
    if not rotated:
        raise HTTPException(401, "刷新令牌已被使用，请重新登录")
    return LoginResponse(
        token=token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        refresh_expires_at=record.expires_at,
    )


@router.post("/auth/logout", status_code=204)
async def logout(claims: Annotated[dict, Depends(require_auth)]) -> Response:
    """撤销当前服务端登录会话；同一会话的访问/刷新令牌全部失效。"""
    await db.revoke_auth_session(str(claims["sid"]))
    return Response(status_code=204)


@router.get("/auth/me", response_model=MeResponse)
async def me(claims: Annotated[dict, Depends(require_auth)]) -> MeResponse:
    exp = claims.get("exp")
    record = await db.get_auth_session(str(claims["sid"]))
    return MeResponse(
        authenticated=True,
        expires_at=datetime.fromtimestamp(exp, tz=UTC) if exp else None,
        refresh_expires_at=record.expires_at if record else None,
    )
