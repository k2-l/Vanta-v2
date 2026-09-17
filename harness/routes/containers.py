"""容器管理 CRUD —— 原 nexus-svc handlers/container.go + services/podman.go 端口。

harness 直连 podman（infra/podman.py，shell CLI），管理容器定义（ContainerRecord）＋实体容器。
GET /containers 反映 live podman 容器 ∪ store 元数据：本 App 建的标 managed=true（可操作生命周期），
外部容器只读展示（managed=false）。写侧（create/start/stop/delete/exec）经 podman + 同步库状态。
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select

from harness.app.auth import require_auth
from harness.infra import podman
from harness.infra.db import ContainerProfile, ContainerRecord, session_factory
from harness.infra.logging import log
from harness.routes._utils import container_to_dict, get_or_404

router = APIRouter(prefix="/v1", tags=["containers"])


class CreateContainerRequest(BaseModel):
    name: str
    image: str
    ports: list[str] = Field(default_factory=list)
    env_vars: list[str] = Field(default_factory=list)
    command: list[str] | None = None
    network_mode: str = "bridge"
    working_dir: str = ""

    @field_validator("network_mode")
    @classmethod
    def validate_network_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"bridge", "none"}:
            raise ValueError("network_mode 仅允许 bridge 或 none")
        return normalized

    @field_validator("working_dir")
    @classmethod
    def validate_working_dir(cls, value: str) -> str:
        normalized = value.strip()
        if normalized and not normalized.startswith("/"):
            raise ValueError("working_dir 必须是容器内绝对路径")
        return normalized


class ExecContainerRequest(BaseModel):
    command: list[str]
    working_dir: str = ""
    env: list[str] = []
    timeout_sec: int = 60
    stdin: str = ""


class ContainerProfileRequest(BaseModel):
    capabilities: list[str] = Field(default_factory=list)
    purpose: str = "generic"
    workspace_mode: str = "none"
    network_policy: str = "none"
    default_workdir: str = ""
    agent_allowlist: list[str] = Field(default_factory=list)
    max_concurrency: int = Field(default=1, ge=1, le=64)
    agent_ready: bool = False

    @field_validator("workspace_mode")
    @classmethod
    def validate_workspace_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"none", "read-only", "read-write"}:
            raise ValueError("workspace_mode 必须是 none、read-only 或 read-write")
        return normalized

    @field_validator("network_policy")
    @classmethod
    def validate_network_policy(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"none", "internet"}:
            raise ValueError("network_policy 必须是 none 或 internet")
        return normalized

    @field_validator("default_workdir")
    @classmethod
    def validate_workdir(cls, value: str) -> str:
        normalized = value.strip()
        if normalized and not normalized.startswith("/"):
            raise ValueError("default_workdir 必须是容器内绝对路径")
        return normalized

    @field_validator("capabilities", "agent_allowlist")
    @classmethod
    def normalize_lists(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for item in value:
            normalized = item.strip().lower()
            if not normalized:
                raise ValueError("列表项不能为空")
            if normalized not in result:
                result.append(normalized)
        return result


def _profile_to_dict(profile: ContainerProfile) -> dict:
    return {
        "container_record_id": profile.container_record_id,
        "capabilities": list(profile.capabilities or []),
        "purpose": profile.purpose,
        "workspace_mode": profile.workspace_mode,
        "network_policy": profile.network_policy,
        "default_workdir": profile.default_workdir,
        "agent_allowlist": list(profile.agent_allowlist or []),
        "max_concurrency": profile.max_concurrency,
        "agent_ready": profile.agent_ready,
        "health_status": profile.health_status,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


@router.get("/containers")
async def list_containers(_: Annotated[dict, Depends(require_auth)]) -> list[dict]:
    """live podman 容器 ∪ store 元数据合并；daemon 不可达则退回 store-only（全 managed）。"""
    async with session_factory()() as db:
        rows = (await db.execute(select(ContainerRecord))).scalars().all()
    by_cid = {r.container_id: r for r in rows if r.container_id}

    try:
        live = await podman.list_containers()
    except Exception as exc:  # noqa: BLE001 —— daemon 不可用：退回 store-only
        log.warning("containers.list.daemon_unavailable", exc=str(exc)[:200])
        return [container_to_dict(r, managed=True) for r in rows]

    views: list[dict] = []
    for lc in live:
        status = podman.normalize_state(lc.state)
        rec = by_cid.get(lc.id)
        if rec is not None:
            views.append(container_to_dict(rec, managed=True, status=status))
        else:
            views.append({
                "id": lc.id, "name": lc.name, "image": lc.image, "status": status,
                "ports": [], "env_vars": [], "container_id": lc.id, "managed": False,
            })
    return views


@router.get("/containers/{cid}")
async def get_container(cid: str, _: Annotated[dict, Depends(require_auth)]) -> dict:
    async with session_factory()() as db:
        rec = await get_or_404(db, ContainerRecord, cid, "容器不存在")
        return container_to_dict(rec)


@router.get("/containers/{cid}/profile")
async def get_container_profile(
    cid: str, _: Annotated[dict, Depends(require_auth)]
) -> dict:
    async with session_factory()() as db:
        await get_or_404(db, ContainerRecord, cid, "容器不存在")
        profile = await db.get(ContainerProfile, cid)
        if profile is None:
            raise HTTPException(404, "容器尚未配置 Agent runtime Profile")
        return _profile_to_dict(profile)


@router.put("/containers/{cid}/profile")
async def put_container_profile(
    cid: str,
    req: ContainerProfileRequest,
    _: Annotated[dict, Depends(require_auth)],
) -> dict:
    """Create/update the explicit opt-in profile used by automatic Agent selection."""
    async with session_factory()() as db:
        rec = await get_or_404(db, ContainerRecord, cid, "容器不存在")
        if req.agent_ready:
            readiness = await podman.probe_agent_runtime(
                rec.container_id,
                working_dir=req.default_workdir,
                require_write=req.workspace_mode == "read-write",
                expected_network_policy=req.network_policy,
            )
            if not readiness.ready:
                log.warning(
                    "container.profile.readiness_rejected",
                    container_record_id=cid,
                    network_policy=req.network_policy,
                    workspace_mode=req.workspace_mode,
                    reason=readiness.reason[:200],
                )
                raise HTTPException(409, readiness.reason)
        profile = await db.get(ContainerProfile, cid)
        if profile is None:
            profile = ContainerProfile(container_record_id=cid)
            db.add(profile)
        profile.capabilities = req.capabilities
        profile.purpose = req.purpose.strip() or "generic"
        profile.workspace_mode = req.workspace_mode
        profile.network_policy = req.network_policy
        profile.default_workdir = req.default_workdir
        profile.agent_allowlist = req.agent_allowlist
        profile.max_concurrency = req.max_concurrency
        profile.agent_ready = req.agent_ready
        profile.health_status = "ready" if req.agent_ready else "disabled"
        await db.commit()
        await db.refresh(profile)
        log.info(
            "container.profile.saved",
            container_record_id=cid,
            agent_ready=profile.agent_ready,
            capability_count=len(profile.capabilities or []),
        )
        return _profile_to_dict(profile)


@router.delete("/containers/{cid}/profile", status_code=204)
async def delete_container_profile(
    cid: str, _: Annotated[dict, Depends(require_auth)]
) -> None:
    from harness.core.runtime_resolver import prepare_container_lifecycle

    if not await prepare_container_lifecycle(cid):
        raise HTTPException(409, "容器正被 Agent invocation 使用，不能删除 Profile")
    async with session_factory()() as db:
        await get_or_404(db, ContainerRecord, cid, "容器不存在")
        result = await db.execute(
            delete(ContainerProfile).where(ContainerProfile.container_record_id == cid)
        )
        if not result.rowcount:
            raise HTTPException(404, "容器尚未配置 Agent runtime Profile")
        await db.commit()


@router.get("/containers/{cid}/readiness")
async def container_readiness(
    cid: str, _: Annotated[dict, Depends(require_auth)]
) -> dict:
    async with session_factory()() as db:
        rec = await get_or_404(db, ContainerRecord, cid, "容器不存在")
        profile = await db.get(ContainerProfile, cid)
    readiness = await podman.probe_agent_runtime(
        rec.container_id,
        working_dir=profile.default_workdir if profile else "",
        require_write=bool(profile and profile.workspace_mode == "read-write"),
        expected_network_policy=profile.network_policy if profile else "",
    )
    return {"ready": readiness.ready, "reason": readiness.reason}


@router.post("/containers", status_code=201)
async def create_container(
    req: CreateContainerRequest,
    _: Annotated[dict, Depends(require_auth)],
) -> dict:
    """建实体 podman 容器 ＋ 库记录。库写失败则回滚删掉刚建的容器（对齐 nexus）。"""
    async with session_factory()() as db:
        existing = await db.scalar(select(ContainerRecord.id).where(ContainerRecord.name == req.name))
    if existing is not None:
        raise HTTPException(409, f"容器名称已存在：{req.name}")

    try:
        podman_id = await podman.create_container(
            req.name,
            req.image,
            req.ports,
            req.env_vars,
            req.command,
            network_mode=req.network_mode,
            working_dir=req.working_dir,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"podman create: {exc}") from exc

    rec = ContainerRecord(
        id=uuid.uuid4().hex[:16], name=req.name, image=req.image, status="created",
        ports=json.dumps(req.ports), env_vars=json.dumps(req.env_vars), container_id=podman_id,
    )
    async with session_factory()() as db:
        db.add(rec)
        try:
            await db.commit()
            await db.refresh(rec)
        except Exception as exc:  # noqa: BLE001 —— 回滚：删掉刚建的 podman 容器
            await podman.remove(podman_id)
            raise HTTPException(500, str(exc)) from exc
    return container_to_dict(rec)


@router.patch("/containers/{cid}/start")
async def start_container(cid: str, _: Annotated[dict, Depends(require_auth)]) -> dict:
    async with session_factory()() as db:
        rec = await get_or_404(db, ContainerRecord, cid, "容器不存在")
        if rec.container_id:
            try:
                await podman.start(rec.container_id)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(500, str(exc)) from exc
        rec.status = "running"
        await db.commit()
        return container_to_dict(rec)


@router.patch("/containers/{cid}/stop")
async def stop_container(cid: str, _: Annotated[dict, Depends(require_auth)]) -> dict:
    from harness.core.runtime_resolver import prepare_container_lifecycle

    if not await prepare_container_lifecycle(cid):
        raise HTTPException(409, "容器正被 Agent invocation 使用，不能停止")
    async with session_factory()() as db:
        rec = await get_or_404(db, ContainerRecord, cid, "容器不存在")
        if rec.container_id:
            try:
                await podman.stop(rec.container_id)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(500, str(exc)) from exc
        rec.status = "stopped"
        await db.commit()
        return container_to_dict(rec)


@router.delete("/containers/{cid}", status_code=204)
async def delete_container(cid: str, _: Annotated[dict, Depends(require_auth)]) -> None:
    from harness.core.runtime_resolver import prepare_container_lifecycle

    if not await prepare_container_lifecycle(cid):
        raise HTTPException(409, "容器正被 Agent invocation 使用，不能删除")
    async with session_factory()() as db:
        rec = await get_or_404(db, ContainerRecord, cid, "容器不存在")
        if rec.container_id:
            await podman.remove(rec.container_id)   # best-effort，不阻断库删除
        await db.execute(delete(ContainerRecord).where(ContainerRecord.id == cid))
        await db.commit()


@router.post("/containers/{cid}/exec")
async def exec_container(
    cid: str,
    req: ExecContainerRequest,
    _: Annotated[dict, Depends(require_auth)],
) -> dict:
    async with session_factory()() as db:
        rec = await get_or_404(db, ContainerRecord, cid, "容器不存在")
    if rec.status != "running":
        raise HTTPException(409, "容器未运行")
    if not req.command:
        raise HTTPException(400, "command 不能为空")
    res = await podman.exec(
        rec.container_id, req.command,
        working_dir=req.working_dir, env=req.env,
        timeout=req.timeout_sec, stdin=req.stdin or None,
    )
    return {"exit_code": res.exit_code, "stdout": res.stdout, "stderr": res.stderr}
