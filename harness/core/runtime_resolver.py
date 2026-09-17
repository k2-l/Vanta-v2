"""Automatic per-invocation container selection for sub-Agents.

The model declares logical requirements; this module owns the authoritative mapping
to a managed container, live readiness checks, concurrency leases and fail-closed
errors.  Agent/Skill file protocols intentionally do not depend on this module.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update

from harness.infra import podman
from harness.infra.db import (
    ContainerLease,
    ContainerProfile,
    ContainerRecord,
    session_factory,
)
from harness.infra.logging import log

VALID_NETWORK_POLICIES = frozenset({"none", "internet"})
VALID_WORKSPACE_MODES = frozenset({"none", "read-only", "read-write"})
LEASE_TTL = timedelta(hours=12)


class RuntimeResolutionError(RuntimeError):
    """A requested runtime cannot be selected without violating policy."""

    def __init__(self, message: str, code: str = "RUNTIME_UNAVAILABLE") -> None:
        super().__init__(message)
        self.code = code


def _normalized_str_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise RuntimeResolutionError(f"{field_name} 必须是字符串数组", "INVALID_RUNTIME_REQUIREMENTS")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise RuntimeResolutionError(
                f"{field_name} 只能包含非空字符串", "INVALID_RUNTIME_REQUIREMENTS"
            )
        name = item.strip().lower()
        if name not in normalized:
            normalized.append(name)
    return tuple(normalized)


@dataclass(frozen=True)
class RuntimeRequirements:
    capabilities: tuple[str, ...] = ()
    network: str = ""
    workspace: str = ""

    @classmethod
    def from_input(cls, raw: dict[str, Any] | None) -> RuntimeRequirements:
        if not isinstance(raw, dict):
            raise RuntimeResolutionError(
                "runtime_requirements 必须是对象", "INVALID_RUNTIME_REQUIREMENTS"
            )
        network = str(raw.get("network") or "").strip().lower()
        workspace = str(raw.get("workspace") or "").strip().lower()
        if network and network not in VALID_NETWORK_POLICIES:
            raise RuntimeResolutionError(
                f"不支持的网络策略：{network}", "INVALID_RUNTIME_REQUIREMENTS"
            )
        if workspace and workspace not in VALID_WORKSPACE_MODES:
            raise RuntimeResolutionError(
                f"不支持的工作区模式：{workspace}", "INVALID_RUNTIME_REQUIREMENTS"
            )
        return cls(
            capabilities=_normalized_str_list(raw.get("capabilities"), "capabilities"),
            network=network,
            workspace=workspace,
        )


@dataclass(frozen=True)
class RuntimeCandidate:
    record_id: str
    podman_id: str
    name: str
    capabilities: tuple[str, ...]
    network_policy: str
    workspace_mode: str
    default_workdir: str
    max_concurrency: int
    agent_ready: bool
    agent_allowlist: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedRuntime:
    execution_env: str
    container_record_id: str
    container_name: str
    working_dir: str
    lease_id: str


def _candidate_from_rows(record: ContainerRecord, profile: ContainerProfile) -> RuntimeCandidate:
    return RuntimeCandidate(
        record_id=record.id,
        podman_id=record.container_id or "",
        name=record.name,
        capabilities=_normalized_str_list(profile.capabilities or [], "profile.capabilities"),
        network_policy=(profile.network_policy or "none").lower(),
        workspace_mode=(profile.workspace_mode or "none").lower(),
        default_workdir=profile.default_workdir or "",
        max_concurrency=max(1, int(profile.max_concurrency or 1)),
        agent_ready=bool(profile.agent_ready),
        agent_allowlist=tuple(
            str(v).strip().lower() for v in (profile.agent_allowlist or []) if str(v).strip()
        ),
    )


def rank_candidates(
    candidates: list[RuntimeCandidate],
    *,
    agent_name: str,
    requirements: RuntimeRequirements,
) -> list[RuntimeCandidate]:
    """Filter hard requirements and rank by least privilege, then stable name."""
    required_caps = set(requirements.capabilities)
    network_rank = {"none": 0, "internet": 1}
    workspace_rank = {"none": 0, "read-only": 1, "read-write": 2}
    eligible: list[RuntimeCandidate] = []
    for candidate in candidates:
        allowlist = set(candidate.agent_allowlist)
        if not candidate.agent_ready or not candidate.podman_id:
            continue
        if "*" not in allowlist and agent_name.lower() not in allowlist:
            continue
        if not required_caps.issubset(set(candidate.capabilities)):
            continue
        if requirements.network and candidate.network_policy != requirements.network:
            continue
        if requirements.workspace and candidate.workspace_mode != requirements.workspace:
            continue
        eligible.append(candidate)

    return sorted(
        eligible,
        key=lambda item: (
            len(set(item.capabilities) - required_caps),
            network_rank.get(item.network_policy, 99),
            workspace_rank.get(item.workspace_mode, 99),
            item.name,
        ),
    )


async def _load_candidates() -> list[RuntimeCandidate]:
    async with session_factory()() as db:
        rows = (
            await db.execute(
                select(ContainerRecord, ContainerProfile).join(
                    ContainerProfile,
                    ContainerProfile.container_record_id == ContainerRecord.id,
                )
            )
        ).all()
    candidates: list[RuntimeCandidate] = []
    for record, profile in rows:
        try:
            candidates.append(_candidate_from_rows(record, profile))
        except RuntimeResolutionError as exc:
            log.warning(
                "runtime.profile_invalid",
                container_id=record.id,
                error=str(exc)[:160],
            )
    return candidates


async def runtime_catalog(agent_name: str = "") -> list[dict[str, Any]]:
    """Return the safe logical capability catalog exposed to the orchestrator model."""
    normalized_agent = agent_name.strip().lower()
    async with session_factory()() as db:
        rows = (
            await db.execute(
                select(ContainerRecord, ContainerProfile).join(
                    ContainerProfile,
                    ContainerProfile.container_record_id == ContainerRecord.id,
                )
            )
        ).all()
    result: list[dict[str, Any]] = []
    for record, profile in rows:
        allowlist = {
            str(item).strip().lower()
            for item in (profile.agent_allowlist or [])
            if str(item).strip()
        }
        if not profile.agent_ready:
            continue
        if normalized_agent and "*" not in allowlist and normalized_agent not in allowlist:
            continue
        result.append(
            {
                "name": record.name,
                "purpose": profile.purpose,
                "capabilities": list(profile.capabilities or []),
                "network": profile.network_policy,
                "workspace": profile.workspace_mode,
                "health": profile.health_status,
                "agents": sorted(allowlist),
                "lifecycle": "persistent-auto-start",
            }
        )
    return sorted(result, key=lambda item: item["name"])


async def _set_health(container_record_id: str, status: str) -> None:
    async with session_factory()() as db:
        await db.execute(
            update(ContainerProfile)
            .where(ContainerProfile.container_record_id == container_record_id)
            .values(health_status=status, updated_at=datetime.now(UTC))
        )
        await db.commit()


async def _set_record_status(container_record_id: str, status: str) -> None:
    """Keep the store fallback consistent with resolver-driven lifecycle changes."""
    async with session_factory()() as db:
        await db.execute(
            update(ContainerRecord)
            .where(ContainerRecord.id == container_record_id)
            .values(status=status, updated_at=datetime.now(UTC))
        )
        await db.commit()


async def _ensure_running(candidate: RuntimeCandidate) -> tuple[bool, str]:
    """Recover an opted-in long-running runtime after an unexpected exit.

    An explicit management API stop disables ``agent_ready`` first, so only profiles
    that remain opted in reach this path. The container stays running after lease
    release, avoiding a cold start for every Agent task.
    """
    if await podman.is_running(candidate.podman_id):
        return True, ""

    await _set_health(candidate.record_id, "starting")
    log.info(
        "runtime.auto_start",
        container_id=candidate.record_id,
        container_name=candidate.name,
    )
    try:
        await podman.start(candidate.podman_id)
    except Exception as exc:  # noqa: BLE001 -- a concurrent resolver may have started it
        if not await podman.is_running(candidate.podman_id):
            return False, f"自动启动失败：{exc}"

    if not await podman.is_running(candidate.podman_id):
        return False, "自动启动后容器未保持运行，请检查镜像 CMD 或长期运行 command"

    await _set_record_status(candidate.record_id, "running")
    log.info(
        "runtime.auto_started",
        container_id=candidate.record_id,
        container_name=candidate.name,
    )
    return True, ""


async def _try_acquire(
    candidate: RuntimeCandidate,
    *,
    session_id: str,
    invocation_id: str,
    agent_name: str,
) -> ContainerLease | None:
    """Serialize acquisitions on the profile row and enforce max_concurrency."""
    now = datetime.now(UTC)
    async with session_factory()() as db:
        profile = await db.scalar(
            select(ContainerProfile)
            .where(ContainerProfile.container_record_id == candidate.record_id)
            .with_for_update()
        )
        if profile is None or not profile.agent_ready:
            return None
        active = await db.scalar(
            select(func.count(ContainerLease.id)).where(
                ContainerLease.container_record_id == candidate.record_id,
                ContainerLease.status == "active",
                ContainerLease.expires_at > now,
            )
        )
        if int(active or 0) >= max(1, int(profile.max_concurrency or 1)):
            return None
        lease = ContainerLease(
            id=uuid.uuid4().hex[:16],
            container_record_id=candidate.record_id,
            session_id=session_id,
            invocation_id=invocation_id,
            agent_name=agent_name,
            status="active",
            acquired_at=now,
            expires_at=now + LEASE_TTL,
        )
        db.add(lease)
        await db.commit()
        await db.refresh(lease)
        return lease


async def resolve_runtime(
    *,
    agent_name: str,
    requirements: RuntimeRequirements,
    session_id: str,
    invocation_id: str,
) -> ResolvedRuntime:
    """Select, live-probe and lease a runtime.  Never falls back to the host."""
    candidates = rank_candidates(
        await _load_candidates(), agent_name=agent_name, requirements=requirements
    )
    if not candidates:
        raise RuntimeResolutionError(
            f"没有与 Agent {agent_name!r} 及运行需求匹配的容器 Profile"
        )

    probe_failures: list[str] = []
    saturated = False
    for candidate in candidates:
        running, start_error = await _ensure_running(candidate)
        if not running:
            probe_failures.append(f"{candidate.name}: {start_error}")
            await _set_health(candidate.record_id, "unavailable")
            continue
        readiness = await podman.probe_agent_runtime(
            candidate.podman_id,
            working_dir=candidate.default_workdir,
            require_write=candidate.workspace_mode == "read-write",
            expected_network_policy=candidate.network_policy,
        )
        if not readiness.ready:
            probe_failures.append(f"{candidate.name}: {readiness.reason}")
            await _set_health(candidate.record_id, "unavailable")
            continue
        await _set_health(candidate.record_id, "ready")
        lease = await _try_acquire(
            candidate,
            session_id=session_id,
            invocation_id=invocation_id,
            agent_name=agent_name,
        )
        if lease is None:
            saturated = True
            continue
        log.info(
            "runtime.resolved",
            agent=agent_name,
            container_id=candidate.record_id,
            lease_id=lease.id,
        )
        return ResolvedRuntime(
            execution_env=f"container:{candidate.record_id}",
            container_record_id=candidate.record_id,
            container_name=candidate.name,
            working_dir=candidate.default_workdir,
            lease_id=lease.id,
        )

    if probe_failures:
        detail = "；".join(probe_failures[:3])
        raise RuntimeResolutionError(f"匹配到的容器均未通过 readiness：{detail}")
    if saturated:
        raise RuntimeResolutionError("匹配到的容器当前均已达到并发上限", "RUNTIME_BUSY")
    raise RuntimeResolutionError("没有可用的 Agent runtime")


async def release_runtime(lease_id: str) -> None:
    if not lease_id:
        return
    now = datetime.now(UTC)
    async with session_factory()() as db:
        await db.execute(
            update(ContainerLease)
            .where(ContainerLease.id == lease_id, ContainerLease.status == "active")
            .values(status="released", released_at=now)
        )
        await db.commit()
    log.info("runtime.released", lease_id=lease_id)


async def prepare_container_lifecycle(container_record_id: str) -> bool:
    """Atomically disable auto-selection before stop/delete/profile removal.

    Locking the profile row closes the race where a new invocation could acquire a
    lease after a route checked for active work but before Podman was stopped.
    """
    now = datetime.now(UTC)
    async with session_factory()() as db:
        profile = await db.scalar(
            select(ContainerProfile)
            .where(ContainerProfile.container_record_id == container_record_id)
            .with_for_update()
        )
        if profile is None:
            return True
        count = await db.scalar(
            select(func.count(ContainerLease.id)).where(
                ContainerLease.container_record_id == container_record_id,
                ContainerLease.status == "active",
                ContainerLease.expires_at > now,
            )
        )
        if count:
            return False
        profile.agent_ready = False
        profile.health_status = "disabled"
        await db.commit()
        return True


async def release_stale_leases() -> int:
    """Release leases left by a previous process; called once during startup."""
    now = datetime.now(UTC)
    async with session_factory()() as db:
        result = await db.execute(
            update(ContainerLease)
            .where(ContainerLease.status == "active")
            .values(status="released", released_at=now)
        )
        await db.commit()
    return int(result.rowcount or 0)
