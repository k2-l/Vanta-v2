"""run_agent 工具 — 派发任务给子 agent 独立执行。

使用场景：
  主代理调用 run_agent("代码审计专家", "审计 /src 目录", context="") 时，
  系统通过 Provider 加载对应 Agent 定义，在独立执行上下文中运行子 agent 图，
  把最终回复文本作为工具结果返回给主代理。

串行 / 并行由主代理的 LLM 自然控制：
  - 同一条 AI 回复里的多个 run_agent 调用 → 并行（tool_node asyncio.gather）
  - 下一轮再调用 → 串行（依赖上一轮结果）
"""

from __future__ import annotations

from typing import Any

from harness.core.graph.subagent import (
    child_invocation_id,
    current_agent_lineage,
    current_invocation_id,
    current_sub_agent_depth,
    enter_agent_invocation,
    enter_sub_agent_depth,
    get_orchestration_context,
    release_delegation,
    reserve_delegation,
    run_sub_agent,
)
from harness.tools.base import Tool, ToolResult
from harness.tools.registry import register


@register
class RunAgentTool(Tool):
    name = "Agent"
    category = "agent"
    description = (
        "把一个子任务派发给指定的专家 Agent 独立执行，返回其最终输出。\n"
        "- 同一轮次多个 Agent 调用会**并行**执行\n"
        "- 需要串行时（后续任务依赖前一个结果），把前一个结果通过 context 参数传入\n"
        "- 主代理和子代理均可委派；每个 invocation 最多同时运行 3 个直接子 Agent，最大深度 3\n"
        "- 任务需要专用环境时，通过 runtime_requirements 声明能力，由后端选择并租用容器；"
        "找不到匹配环境时不会回退本机\n"
        "- 只能调用已启动（active=true）的 Agent"
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Agent 名称（如 code-audit-expert）",
            },
            "task": {
                "type": "string",
                "description": "要执行的任务描述",
            },
            "context": {
                "type": "string",
                "description": "上游 agent 的输出（串行依赖时传入），默认为空",
            },
            "runtime_requirements": {
                "type": "object",
                "description": (
                    "可选。存在时为本次子 Agent 自动选择隔离容器；省略则继承父执行环境。"
                ),
                "properties": {
                    "capabilities": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "所需能力标签，如 jdk17、semgrep、sqlmap",
                    },
                    "network": {
                        "type": "string",
                        "enum": ["none", "internet"],
                        "description": (
                            "普通任务所需网络策略；主动扫描会由权限层另行路由到 engagement 沙箱"
                        ),
                    },
                    "workspace": {
                        "type": "string",
                        "enum": ["none", "read-only", "read-write"],
                        "description": "所需工作区挂载模式",
                    },
                },
                "additionalProperties": False,
            },
        },
        "required": ["name", "task"],
    }

    async def run(
        self,
        name: str,
        task: str,
        context: str = "",
        runtime_requirements: dict[str, Any] | None = None,
    ) -> ToolResult:
        from harness.core.runtime_resolver import RuntimeRequirements, RuntimeResolutionError
        from harness.infra.settings import get_settings
        from harness.providers import get_provider

        s = get_settings()
        current_depth = current_sub_agent_depth()
        parent_id = current_invocation_id()
        lineage = current_agent_lineage()

        requirements = None
        if runtime_requirements is not None:
            try:
                requirements = RuntimeRequirements.from_input(runtime_requirements)
            except RuntimeResolutionError as exc:
                return ToolResult.fail(error=str(exc), error_code=exc.code)

        # ── 深度限制 ────────────────────────────────────────────────────
        if current_depth >= s.sub_agent_max_depth:
            return ToolResult.fail(
                error=f"已达到最大调用深度 (depth={current_depth}，上限={s.sub_agent_max_depth})，"
                f"拒绝继续派发",
                error_code="DEPTH_LIMIT",
            )

        if name in lineage:
            return ToolResult.fail(
                error=f"检测到 Agent 委派循环：{' → '.join((*lineage, name))}",
                error_code="DELEGATION_CYCLE",
            )

        # ── 加载 Agent 定义（统一协议：EntityProvider.get，直接消费 AgentFull）──
        try:
            agent = get_provider("agent").get(name)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.fail(
                error=f"加载 Agent '{name}' 时出错：{exc}",
                error_code="LOAD_ERROR",
            )
        if agent is None:
            return ToolResult.fail(
                error=f"Agent '{name}' 不存在",
                error_code="AGENT_NOT_FOUND",
            )

        limit_error = await reserve_delegation(
            parent_id,
            s.max_agent_delegations_per_agent,
        )
        if limit_error == "DELEGATION_LIMIT":
            return ToolResult.fail(
                error=(
                    f"当前 Agent invocation 最多同时运行 "
                    f"{s.max_agent_delegations_per_agent} 个子 Agent"
                ),
                error_code=limit_error,
            )
        if limit_error:
            return ToolResult.fail(
                error=f"本轮 Agent invocation 总数已达上限 {s.max_agent_invocations_per_turn}",
                error_code=limit_error,
            )

        # ── 递增深度，执行子 agent；不整图重试，避免重放工具副作用 ────────
        import structlog

        invocation_id = child_invocation_id(parent_id)
        try:
            with enter_sub_agent_depth() as new_depth:
                from harness.infra.logging import log

                log.info(
                    "run_agent.start",
                    agent=name,
                    depth=new_depth,
                    invocation_id=invocation_id,
                    task_preview=task[:80],
                )

                # 从调用链获取 session_id / trace_id（通过 LangGraph RunnableConfig
                # 传递的 configurable 字段；未设置时降级为占位符）
                ctx = structlog.contextvars.get_contextvars()
                session_id = ctx.get("session_id", "_anon")
                trace_id = ctx.get("trace", "")

                try:
                    async def invoke_sub_agent() -> str:
                        from harness.core.runtime_resolver import release_runtime, resolve_runtime

                        resolved = None
                        try:
                            if requirements is not None:
                                resolved = await resolve_runtime(
                                    agent_name=name,
                                    requirements=requirements,
                                    session_id=session_id,
                                    invocation_id=invocation_id,
                                )
                            return await run_sub_agent(
                                agent=agent,
                                task=task,
                                context=context,
                                depth=new_depth,
                                session_id=session_id,
                                trace_id=trace_id,
                                invocation_id=invocation_id,
                                parent_invocation_id=parent_id,
                                lineage=(*lineage, name),
                                execution_env=(resolved.execution_env if resolved else None),
                            )
                        finally:
                            if resolved is not None:
                                try:
                                    await release_runtime(resolved.lease_id)
                                except Exception as exc:  # noqa: BLE001 -- 不用清理故障覆盖任务结果
                                    from harness.infra.logging import log

                                    log.error(
                                        "run_agent.runtime_release_failed",
                                        lease_id=resolved.lease_id,
                                        error=str(exc)[:200],
                                    )

                    orchestration = get_orchestration_context()
                    with enter_agent_invocation(invocation_id, name):
                        # 只对主代理直接派发的根子任务做全局并发门控；若父任务持有
                        # permit 时嵌套子任务也抢同一 semaphore，会形成层级死锁。
                        if orchestration is None or current_depth > 0:
                            result_text = await invoke_sub_agent()
                        else:
                            async with orchestration.semaphore:
                                result_text = await invoke_sub_agent()
                    log.info(
                        "run_agent.done",
                        agent=name,
                        depth=new_depth,
                        invocation_id=invocation_id,
                        output_len=len(result_text),
                    )
                    return ToolResult(ok=True, output=result_text)
                except RuntimeResolutionError as exc:
                    log.warning(
                        "run_agent.runtime_unavailable",
                        agent=name,
                        invocation_id=invocation_id,
                        error=str(exc)[:300],
                    )
                    return ToolResult.fail(error=str(exc), error_code=exc.code)
                except Exception as exc:  # noqa: BLE001
                    log.error(
                        "run_agent.error",
                        agent=name,
                        depth=new_depth,
                        invocation_id=invocation_id,
                        exc=str(exc)[:300],
                    )
                    return ToolResult.fail(
                        error=f"子 Agent '{name}' 执行失败：{exc}",
                        error_code="SUB_AGENT_ERROR",
                    )
        finally:
            # 直接配额表示并发槽，不是整回合次数；取消、成功或失败都必须释放。
            await release_delegation(parent_id)
