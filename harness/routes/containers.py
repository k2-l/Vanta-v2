"""容器管理 CRUD —— 原 nexus-svc handlers/container.go + services/podman.go 端口。

harness 直连 podman（infra/podman.py，shell CLI），管理容器定义（ContainerRecord）＋实体容器。
GET /containers 反映 live podman 容器 ∪ store 元数据：本 App 建的标 managed=true（可操作生命周期），
外部容器只读展示（managed=false）。写侧（create/start/stop/delete/exec）经 podman + 同步库状态。
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select

from harness.app.auth import require_auth
from harness.infra import podman
from harness.infra.db import ContainerRecord, session_factory
from harness.infra.logging import log
from harness.routes._utils import container_to_dict, get_or_404

router = APIRouter(prefix="/v1", tags=["containers"])


class CreateContainerRequest(BaseModel):
    name: str
    image: str
    ports: list[str] = []
    env_vars: list[str] = []


class ExecContainerRequest(BaseModel):
    command: list[str]
    working_dir: str = ""
    env: list[str] = []
    timeout_sec: int = 60
    stdin: str = ""


@router.get("/containers")
async def list_containers(_: dict = Depends(require_auth)) -> list[dict]:
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
async def get_container(cid: str, _: dict = Depends(require_auth)) -> dict:
    async with session_factory()() as db:
        rec = await get_or_404(db, ContainerRecord, cid, "容器不存在")
        return container_to_dict(rec)


@router.post("/containers", status_code=201)
async def create_container(req: CreateContainerRequest, _: dict = Depends(require_auth)) -> dict:
    """建实体 podman 容器 ＋ 库记录。库写失败则回滚删掉刚建的容器（对齐 nexus）。"""
    try:
        podman_id = await podman.create_container(req.name, req.image, req.ports, req.env_vars)
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
async def start_container(cid: str, _: dict = Depends(require_auth)) -> dict:
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
async def stop_container(cid: str, _: dict = Depends(require_auth)) -> dict:
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
async def delete_container(cid: str, _: dict = Depends(require_auth)) -> None:
    async with session_factory()() as db:
        rec = await get_or_404(db, ContainerRecord, cid, "容器不存在")
        if rec.container_id:
            await podman.remove(rec.container_id)   # best-effort，不阻断库删除
        await db.execute(delete(ContainerRecord).where(ContainerRecord.id == cid))
        await db.commit()


@router.post("/containers/{cid}/exec")
async def exec_container(
    cid: str, req: ExecContainerRequest, _: dict = Depends(require_auth)
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
