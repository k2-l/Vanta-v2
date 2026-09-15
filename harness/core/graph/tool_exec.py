"""tool_exec — 单次工具调用的共享执行内核。

主图(nodes.tool_node)与子图(subgraph)的工具执行器都委托到 execute_tool_core，
消除两份 ~80% 重复实现。各自的策略外壳（缓存/压缩/失败计数 vs 白名单/主代理专属拦截）
保留在各自侧；本内核只负责"安全地跑一个工具并包装结果"。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path

from langchain_core.messages import ToolMessage

from harness.core.foundation.errors import classify_error
from harness.infra.logging import log
from harness.infra.metrics import inc as _inc
from harness.infra.settings import get_settings
from harness.security.approvals import (
    classify_risk,
    describe_impact,
    describe_scope,
    describe_target,
    request_approval,
)
from harness.security.audit_agent import audit_review
from harness.security.permissions import active_policy, evaluate
from harness.security.redaction import redact
from harness.tools.exec_context import ExecEnv, get_exec_env
from harness.tools.registry import registry
from harness.tools.sanitizer import injection_flags, sanitize_tool_output


def _ask_message(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Bash":
        return f"执行命令：{str(tool_input.get('command', ''))[:200]}？"
    return f"执行工具 {tool_name}？"


def disclosed_from_tool_calls(tool_calls: list[dict]) -> list[str]:
    """从本轮 tool_calls 里的 tool_search 调用复算命中的 dynamic 工具名（去重保序）。

    披露-可调用机制的写回侧：tool_search 工具本身只产出给模型看的清单文本，
    真正把命中名累加进 state["disclosed_tools"] 的副作用在此完成 —— 对同一
    (query, limit) 复用 registry.match_dynamic（与工具内部同一函数），结果必然一致，
    无需解析工具输出字符串。两个 tool_node 共用，供其把返回值 merge 进 disclosed_tools。
    """
    seen: set[str] = set()
    out: list[str] = []
    for tc in tool_calls:
        if tc.get("name") != "tool_search":
            continue
        args = tc.get("args") or {}
        if not isinstance(args, dict):
            continue
        query = str(args.get("query", ""))
        try:
            limit = int(args.get("limit", 10))
        except (TypeError, ValueError):
            limit = 10
        for name in registry.match_dynamic(query, limit):
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


def _persist_and_truncate(raw: str, tool_name: str, max_output_chars: int) -> str:
    """大工具输出落盘 + 返回「截断版正文 + Read 指针路径」，防止把几 MB 扫描日志灌进上下文。

    完整内容写到 workspace/.tool_outputs/<tool>-<hash>.txt，模型可用 Read 工具读回被截断部分。
    落盘失败则退回纯截断（不影响主流程）。同步 IO，与 _read_profile_file 同款取舍。
    """
    head = raw[:max_output_chars]
    try:
        ws = Path(get_settings().workspace_dir or ".").resolve()
        output_dir = ws / ".tool_outputs"
        output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        output_dir.chmod(0o700)
        digest = hashlib.md5(raw.encode("utf-8", "replace")).hexdigest()[:12]
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", tool_name)[:40] or "tool"
        rel = f".tool_outputs/{safe}-{digest}.txt"
        output_path = ws / rel
        output_path.write_text(raw, encoding="utf-8")
        output_path.chmod(0o600)
        return (
            head
            + f"\n\n…[输出过长（共 {len(raw)} 字符），已截断至 {max_output_chars}。"
            f"完整内容已落盘，如需被截断部分请用 Read 工具读取：{rel}]"
        )
    except Exception as exc:  # noqa: BLE001 — 落盘失败退回纯截断
        return head + f"\n…[输出过长，已截断至 {max_output_chars} 字符（落盘失败 {type(exc).__name__}）]"


# engagement 期间落审计账本的"会碰目标/系统"动作（其余内部工具不刷账本）
_AUDITABLE_ACTIONS: frozenset[str] = frozenset({"Bash", "WebFetch", "WebSearch"})


async def _audit_action(
    env: ExecEnv, tool_name: str, tool_input: dict, decision: str, session_id: str
) -> None:
    """engagement 期间把 Bash/WebFetch/WebSearch 动作落审计账本。fail-safe（审计失败不阻断）。"""
    if not env.has_engagement or tool_name not in _AUDITABLE_ACTIONS:
        return
    command = str(tool_input.get("command", "")) if isinstance(tool_input, dict) else ""
    target = ""
    if isinstance(tool_input, dict):
        target = str(tool_input.get("url") or tool_input.get("target") or "")
    from harness.security.audit_ledger import append_audit

    await append_audit(
        action=tool_name,
        engagement_id=env.engagement_id,
        session_id=session_id,
        target=target[:500],
        command=command[:500],
        decision=decision,
    )


async def execute_tool_core(
    tool_name: str,
    tool_input: dict,
    *,
    sem: asyncio.Semaphore,
    timeout: float | None,  # noqa: ASYNC109 — locked-in shared kernel signature, see module docstring
    max_output_chars: int,
    log_event: str,
    metric_prefix: str,
    trace_id: str = "",
    session_id: str = "",
) -> tuple[str, str | None, str | None, list[str], list[str]]:
    """跑一个工具调用，返回 (content, error_code, error_str, flags, logs)。

    - timeout=None 表示不限时（asyncio.wait_for(coro, None) 等价于直接 await）。
    - logs 只含一行"← ..."结果日志；调用方自己负责前置的"→ ..."行。
    - 不组装 ToolMessage、不做缓存/白名单/失败计数——那些是调用方的策略外壳。
    - tool.requires_approval=True 时先走 HITL 审批门（harness/infra/approvals.py），
      拒绝/超时返回 error_code="APPROVAL_REJECTED"，不执行 tool.run()。
    """
    content = f"[ERROR] 工具 {tool_name!r} 未执行"
    error_code: str | None = None
    error_str: str | None = None
    flags: list[str] = []
    logs: list[str] = []
    try:
        tool = registry.get(tool_name)

        # 权限门（ADR-0003 P3）：按 allow / ask / deny 决策
        _mode, _rules = active_policy()
        xenv = get_exec_env()
        decision = evaluate(
            tool_name, tool_input, mode=_mode, env=xenv.kind, engaged=xenv.has_engagement, rules=_rules
        )
        if tool.requires_approval and decision == "allow":
            decision = "ask"  # 工具自带的强制审批：至少升级为 ask
        if decision == "deny":
            error_code = "PERMISSION_DENIED"
            content = f"[DENIED] 工具 {tool_name!r} 被权限策略拒绝执行"
            error_str = f"{tool_name}: denied by permission policy"
            logs.append(f"← {tool_name}: ✗ (权限拒绝)")
            await _audit_action(xenv, tool_name, tool_input, "deny", session_id)
            return content, error_code, error_str, flags, logs
        if decision == "ask":
            if tool.requires_approval:
                try:
                    approval_msg = tool.approval_message.format(**{**tool_input, "tool_name": tool_name})
                except (KeyError, IndexError):
                    approval_msg = tool.approval_message
            else:
                approval_msg = _ask_message(tool_name, tool_input)
            # 审批方：audit_agent=LLM 自动裁决（默认放行、只拦破坏性），否则阻塞式人工审批
            if get_settings().approval_reviewer == "audit_agent":
                approved, comment = await audit_review(session_id, tool_name, tool_input, approval_msg)
                if not approved:
                    error_code = "APPROVAL_REJECTED"
                    content = f"[BLOCKED] 审计 Agent 拒绝执行工具 {tool_name!r}：{comment}"
                    error_str = f"{tool_name}: audit rejected — {comment}"
                    logs.append(f"← {tool_name}: ✗ (审计拒绝: {comment[:60]})")
                    return content, error_code, error_str, flags, logs
                logs.append(f"← {tool_name}: 审计放行 ({comment[:60]})")
            else:
                # 阻塞式人工审批：派生风险/对象/范围/影响，供 HITL 卡片如实展示（规范 §4.3）。
                # 工具可通过 approval_context 提供精确规则，未提供的键走通用派生。
                level, risk_source = classify_risk(tool.category, tool.risk_level)
                ctx = tool.approval_context(tool_input)
                approved = await request_approval(
                    session_id,
                    tool_name,
                    approval_msg,
                    risk=level,
                    risk_source=risk_source,
                    target=ctx.get("target") or describe_target(tool_input),
                    scope=ctx.get("scope")
                    or describe_scope(
                        kind=xenv.kind,
                        container_id=xenv.container_id,
                        engagement_id=xenv.engagement_id,
                    ),
                    impact=ctx.get("impact") or describe_impact(level),
                )
                if not approved:
                    error_code = "APPROVAL_REJECTED"
                    content = f"[CANCELLED] 工具 {tool_name!r} 的执行已被拒绝或超时未审批"
                    error_str = f"{tool_name}: approval rejected/timeout"
                    logs.append(f"← {tool_name}: ✗ (审批拒绝/超时)")
                    return content, error_code, error_str, flags, logs

        async with sem:
            result = await asyncio.wait_for(tool.run(**tool_input), timeout=timeout)
        if result.ok:
            # 无论是否处于 engagement，先统一脱敏，再喂给模型或写入大输出文件。
            raw, _ = redact(result.output)
            if len(raw) > max_output_chars:
                raw = _persist_and_truncate(raw, tool_name, max_output_chars)
            flags = injection_flags(raw, tool_name)
            content = sanitize_tool_output(raw, tool_name)
            if flags:
                log.warning(f"{log_event}.injection", tool=tool_name, flags=flags, trace=trace_id)
                _inc("injection.detected")
        else:
            error_code = result.error_code or classify_error(result.error or "")
            content = f"[ERROR:{error_code}] {result.error}"
            error_str = f"{tool_name}: {result.error}"
        await _audit_action(xenv, tool_name, tool_input, "executed" if result.ok else "failed", session_id)
        logs.append(f"← {tool_name}: {'✓' if result.ok else '✗'} ({len(str(content))} 字符)")
    except KeyError:
        error_code = "COMMAND_NOT_FOUND"
        content = f"[ERROR:{error_code}] 未注册的工具：{tool_name}"
        error_str = content
        logs.append(f"← {tool_name}: ✗ (未注册)")
    except TimeoutError:
        error_code = "TIMEOUT"
        content = f"[ERROR:TIMEOUT] 工具 {tool_name!r} 超时（>{timeout}s）"
        error_str = content
        logs.append(f"← {tool_name}: ✗ (超时)")
    except Exception as exc:  # noqa: BLE001
        error_code = classify_error(str(exc))
        content = f"[ERROR:{error_code}] {type(exc).__name__}: {exc}"
        error_str = str(exc)
        logs.append(f"← {tool_name}: ✗ ({type(exc).__name__})")
    finally:
        ok = not error_code
        log.info(
            log_event,
            name=tool_name,
            ok=ok,
            error_code=error_code,
            exc=error_str[:300] if error_str else None,
        )
        _inc(f"{metric_prefix}.ok" if ok else f"{metric_prefix}.fail")
    return content, error_code, error_str, flags, logs


def collect_tool_results(
    tool_calls: list[dict],
    raw: list,
) -> tuple[list[ToolMessage], list[str], list[str], list[str]]:
    """整理 asyncio.gather(return_exceptions=True) 的结果。

    返回 (tool_messages, ordered_logs, errors, failed_tool_names)：
      - asyncio.CancelledError → "[ERROR:CANCELLED] 工具调用已被用户取消"
      - 其他 BaseException     → "[ERROR] {type}: {exc}"
      - 正常 (ToolMessage, logs, error_str|None) → 收集；error_str 非空计入 errors
    每个产生错误（含崩溃/取消）的工具名进入 failed_tool_names，供主图累加失败计数；
    子图不维护失败计数，忽略该返回值即可。
    """
    tool_messages: list[ToolMessage] = []
    ordered_logs: list[str] = []
    errors: list[str] = []
    failed: list[str] = []
    for tc, res in zip(tool_calls, raw, strict=False):
        tc_name = tc.get("name", "")
        tc_id = tc.get("id", "")
        if isinstance(res, asyncio.CancelledError):
            tool_messages.append(
                ToolMessage(content="[ERROR:CANCELLED] 工具调用已被用户取消", tool_call_id=tc_id, name=tc_name)
            )
            ordered_logs.append(f"← {tc_name}: ✗ (已取消)")
            errors.append(f"{tc_name}: 已取消")
            failed.append(tc_name)
        elif isinstance(res, BaseException):
            err_str = f"{type(res).__name__}: {res}"
            tool_messages.append(
                ToolMessage(content=f"[ERROR] {err_str}", tool_call_id=tc_id, name=tc_name)
            )
            ordered_logs.append(f"← {tc_name}: ✗ ({type(res).__name__})")
            errors.append(err_str)
            failed.append(tc_name)
        else:
            msg, logs, err = res
            tool_messages.append(msg)
            ordered_logs.extend(logs)
            if err:
                errors.append(err)
                failed.append(tc_name)
    return tool_messages, ordered_logs, errors, failed


def skipped_tool_messages(orphan_tool_calls: list[dict]) -> list[ToolMessage]:
    """给被 max_tool_calls_per_turn 截断、未执行的 tool_call 补一条合成 tool_result。

    Anthropic 要求每个 tool_use 都有配对的 tool_result；tool_node 把 tool_calls 截断后，
    超出上限的 tool_use 若无对应结果，下一轮把这段历史发回模型会直接 400（悬空 tool_use）。
    这里给每个被跳过的调用补一条"已跳过"结果，使配对完整、并提示模型可下一轮重发。
    借鉴 CSA orphan_tool_pruner 的思路，改为补合成结果而非改写历史，契合追加式消息流。
    """
    return [
        ToolMessage(
            content=(
                "[SKIPPED] 本轮工具调用数超过上限（max_tool_calls_per_turn），"
                "此调用未执行；如仍需要，请在下一轮重新发起。"
            ),
            tool_call_id=tc.get("id", ""),
            name=tc.get("name", ""),
            additional_kwargs={"skipped": True},
        )
        for tc in orphan_tool_calls
    ]
