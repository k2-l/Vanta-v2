"""Opt-in real Podman + PostgreSQL smoke test for Agent runtime selection.

Run from the repository root with an isolated database and a pre-created runtime:

    VANTA_E2E_RUNTIME_NAME=... HARNESS_DATABASE_URL=... python tests/e2e_container_runtime.py

This file is intentionally not named ``test_*.py`` so normal unit discovery never
touches the host container daemon or a real database.
"""

from __future__ import annotations

import asyncio
import json
import os

from sqlalchemy import func, select

from harness.core.runtime_resolver import (
    RuntimeRequirements,
    RuntimeResolutionError,
    prepare_container_lifecycle,
    release_runtime,
    resolve_runtime,
    runtime_catalog,
)
from harness.infra import db, podman
from harness.infra.db import ContainerLease, ContainerProfile, ContainerRecord


async def main() -> None:
    runtime_name = os.environ.get("VANTA_E2E_RUNTIME_NAME", "").strip()
    if not runtime_name:
        raise SystemExit("VANTA_E2E_RUNTIME_NAME is required")

    await db.init_db()
    live = next(
        (item for item in await podman.list_containers() if item.name == runtime_name),
        None,
    )
    if live is None:
        raise RuntimeError(f"runtime container not found: {runtime_name}")

    record_id = "e2e-runtime-record"
    async with db.session_factory()() as session:
        record = ContainerRecord(
            id=record_id,
            name=runtime_name,
            image=live.image,
            status="running",
            ports="[]",
            env_vars="[]",
            container_id=live.id,
        )
        profile = ContainerProfile(
            container_record_id=record_id,
            capabilities=["alpine", "shell"],
            purpose="runtime-e2e",
            workspace_mode="none",
            network_policy="none",
            default_workdir="",
            agent_allowlist=["e2e-agent"],
            max_concurrency=1,
            agent_ready=True,
            health_status="unknown",
        )
        session.add(record)
        await session.flush()
        session.add(profile)
        await session.commit()

    readiness = await podman.probe_agent_runtime(
        live.id, expected_network_policy="none"
    )
    if not readiness.ready:
        raise RuntimeError(readiness.reason)

    catalog = await runtime_catalog("e2e-agent")
    if len(catalog) != 1 or catalog[0]["capabilities"] != ["alpine", "shell"]:
        raise RuntimeError(f"unexpected runtime catalog: {catalog!r}")

    requirements = RuntimeRequirements.from_input(
        {"capabilities": ["shell"], "network": "none", "workspace": "none"}
    )
    first = await resolve_runtime(
        agent_name="e2e-agent",
        requirements=requirements,
        session_id="e2e-session",
        invocation_id="e2e-invocation-1",
    )
    try:
        execution = await podman.exec_record(
            first.container_record_id,
            ["sh", "-c", "printf vanta-runtime-e2e"],
        )
        if execution.exit_code != 0 or execution.stdout != "vanta-runtime-e2e":
            raise RuntimeError(f"unexpected exec result: {execution!r}")

        if await prepare_container_lifecycle(record_id):
            raise RuntimeError("active lease did not block container lifecycle")

        try:
            await resolve_runtime(
                agent_name="e2e-agent",
                requirements=requirements,
                session_id="e2e-session",
                invocation_id="e2e-invocation-2",
            )
        except RuntimeResolutionError as exc:
            if exc.code != "RUNTIME_BUSY":
                raise
        else:
            raise RuntimeError("max_concurrency=1 did not reject a second lease")
    finally:
        await release_runtime(first.lease_id)

    if not await prepare_container_lifecycle(record_id):
        raise RuntimeError("released lease still blocks container lifecycle")

    async with db.session_factory()() as session:
        released = await session.scalar(
            select(func.count(ContainerLease.id)).where(
                ContainerLease.container_record_id == record_id,
                ContainerLease.status == "released",
            )
        )
    if int(released or 0) != 1:
        raise RuntimeError(f"expected one released lease, got {released}")

    print(
        json.dumps(
            {
                "ok": True,
                "runtime": runtime_name,
                "catalog_entries": len(catalog),
                "exec_output": execution.stdout,
                "released_leases": int(released or 0),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
