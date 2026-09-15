/**
 * 浏览器开发用 mock IPC——仅在无 Tauri host 时启用。
 *
 * 目的：让前端在 `npm run dev`（普通浏览器）下独立开发与走查 UI，
 * 不代表真实后端行为，也绝不持有真实凭据。连接/凭据/会话仅存内存。
 * G2 起额外模拟真实事件序列（phase / tool / usage / worker）与 phases 快照。
 */

import type { ConnectionProfile, ServerCapabilities } from "@/contracts/connection";
import type { ChatMessage, SessionSummary } from "@/contracts/chat";
import type { PhaseSnapshotRow, RunEventWire, RunSummaryWire, StreamPacket } from "@/contracts/stream";
import type { ApprovalDecisionRecord, ApprovalWire, ArtifactWire } from "@/contracts/resources";
import type { IpcContract } from "@/contracts/ipc";
import type { StartChatArgs } from "./chat";
import type { RunSubscribeArgs } from "./run";

/** 与后端 G2 声明对齐：phases 快照可用，事件按序重放 / 服务端取消尚不支持。 */
const MOCK_CAPS: ServerCapabilities = {
  apiVersion: "1",
  runSnapshot: true,
  runHistory: true,
  eventReplay: false,
  runCancel: false,
  artifactExport: true,
};

/** 能力目录 mock——形状对齐后端 /v1/{agents,skills,mcp/servers,knowledge,containers}。 */
const MOCK_CAPABILITIES = {
  agents: [
    { id: "orchestrator", name: "orchestrator", description: "统一安全测试调度器，路由白盒 / 黑盒 / 灰盒", model: "claude-opus-4-8", provider: "anthropic", tools: [], skills: [] },
    { id: "audit-analyst", name: "audit-analyst", description: "白盒深度分析：数据流追踪与可利用性判定", model: "claude-sonnet-5", provider: "anthropic", tools: [], skills: [] },
    { id: "pentest-analyst", name: "pentest-analyst", description: "黑盒 / 灰盒渗透，从侦察到后渗透", model: "claude-sonnet-5", provider: "anthropic", tools: [], skills: [] },
  ],
  skills: [
    { id: "passive-recon", name: "passive-recon", description: "被动资产收集与指纹归并", effort: "medium", context: "backend", triggers: [] },
    { id: "sqlmap-runner", name: "sqlmap-runner", description: "在隔离容器内运行 sqlmap 验证注入", effort: "high", context: "container", triggers: [] },
  ],
  mcp: [
    { name: "filesystem", command: "npx @modelcontextprotocol/server-filesystem", args: [], enabled: true, env_keys: [], status: "connected", error: null, tool_count: 6 },
    { name: "http-probe", command: "python -m http_probe", args: [], enabled: true, env_keys: [], status: "disconnected", error: null, tool_count: 0 },
    { name: "legacy-scan", command: "./legacy", args: [], enabled: false, env_keys: [], status: "disconnected", error: null, tool_count: 0 },
  ],
  knowledge: [
    { id: "kb1", name: "evolved-web-vulns", title: "Web 漏洞经验库（蒸馏后模式）", category: "web", content: "", tags: ["xss", "sqli", "idor"] },
    { id: "kb2", name: "evolved-ad-attacks", title: "AD 横向经验库", category: "infra", content: "", tags: ["kerberos", "ntlm"] },
  ],
  containers: [
    { id: "c1", name: "kali-isolated", image: "kali-rolling", status: "running", managed: true, container_id: "abc123" },
    { id: "c2", name: "sqlmap-runner", image: "sqlmap:latest", status: "exited", managed: true, container_id: "def456" },
  ],
};

const store: {
  connections: ConnectionProfile[];
  authed: Set<string>;
  sessions: SessionSummary[];
  messages: Record<string, ChatMessage[]>;
  phases: Record<string, PhaseSnapshotRow[]>;
  events: Record<string, RunEventWire[]>;
  approvals: ApprovalWire[];
  decisions: ApprovalDecisionRecord[];
  artifacts: ArtifactWire[];
} = {
  connections: [
    {
      id: "local-dev",
      label: "本地后端",
      baseUrl: "http://127.0.0.1:8765",
      tlsPolicy: "system",
      lastKnownVersion: "mock",
    },
  ],
  authed: new Set(),
  sessions: [
    {
      id: "session-mock",
      title: "审计 target-api 的认证与越权面",
      created_at: new Date(Date.now() - 42 * 60_000).toISOString(),
      updated_at: new Date(Date.now() - 6 * 60_000).toISOString(),
    },
  ],
  messages: {
    "session-mock": [
      {
        id: "message-mock",
        role: "assistant",
        content: "这是浏览器 mock 会话。连接真实 Tauri Core 后，消息会由后端流式返回。",
        created_at: new Date(Date.now() - 6 * 60_000).toISOString(),
      },
    ],
  },
  phases: {
    "session-mock": buildPhaseTree("session-mock", "审计 target-api 的认证与越权面", "ok"),
  },
  events: {
    "session-mock": buildRunHistory(),
  },
  approvals: [
    {
      call_id: "apr_a1b2c3",
      tool_name: "nmap",
      message: "对 10.2.0.14 执行主动端口扫描（TCP 1-1024，单主机单次）",
      session_id: "session-mock",
      requested_at: new Date(Date.now() - 2 * 60_000).toISOString(),
      expires_at: new Date(Date.now() + 3 * 60_000).toISOString(),
      risk: "high",
      risk_source: "declared",
      target: "10.2.0.14",
      scope: "隔离容器 · 授权范围 eng-mock",
      impact: "将对目标执行主动 / 写入类操作，需明确授权",
    },
    {
      call_id: "apr_d4e5f6",
      tool_name: "http_probe",
      message: "向 https://target-api.internal/login 提交注入验证请求（只读探测）",
      session_id: "session-mock",
      requested_at: new Date(Date.now() - 40_000).toISOString(),
      expires_at: new Date(Date.now() + 4 * 60_000).toISOString(),
      risk: "medium",
      risk_source: "derived",
      target: "https://target-api.internal/login",
      scope: "本机 · 授权范围 eng-mock",
      impact: "将访问外部资源或写入文件系统",
    },
  ],
  decisions: [
    {
      decision_id: "dec_mock01",
      call_id: "apr_seed01",
      tool_name: "shell",
      session_id: "session-mock",
      decision: "rejected",
      risk: "high",
      risk_source: "derived",
      target: "rm -rf ./build",
      scope: "本机 · 无活跃 engagement",
      impact: "可造成破坏性或不可逆操作，务必确认授权范围",
      message: "确认执行工具 shell？",
      decided_at: new Date(Date.now() - 18 * 60_000).toISOString(),
      entry_hash: "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
    },
    {
      decision_id: "dec_mock_expired",
      call_id: "apr_expired01",
      tool_name: "shell",
      session_id: "session-mock",
      decision: "expired",
      risk: "high",
      risk_source: "derived",
      target: "./release.sh",
      scope: "本机 · 授权范围 eng-mock",
      impact: "将对目标执行主动 / 写入类操作，需明确授权",
      message: "执行发布脚本",
      requested_at: new Date(Date.now() - 12 * 60_000).toISOString(),
      expires_at: new Date(Date.now() - 7 * 60_000).toISOString(),
      decided_at: new Date(Date.now() - 7 * 60_000).toISOString(),
      audit_recorded: true,
      entry_hash: "b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3",
    },
  ],
  artifacts: [
    {
      id: "art_finding_1",
      engagement_id: "eng-mock",
      producer: "java-auditor",
      kind: "finding",
      sensitivity: "internal",
      title: "H-01 认证绕过：/login 未复核 role 声明",
      content: "## H-01 认证绕过\n\n`/login` 直接信任请求体中的 `role` 字段，未与服务端会话核对，可越权提升为管理员。\n\n- 影响：越权访问\n- 证据：见请求/响应对\n- 建议：服务端强制以会话身份为准",
      tags: ["auth", "idor"],
      vault_ref: "",
      severity: "high",
      status: "open",
      created_at: new Date(Date.now() - 5 * 60_000).toISOString(),
      updated_at: new Date(Date.now() - 4 * 60_000).toISOString(),
      source_session_id: "session-mock",
      source_run_id: "session-mock",
      media_type: "text/markdown",
      size_bytes: 238,
    },
    {
      id: "art_note_1",
      engagement_id: "eng-mock",
      producer: "audit-analyst",
      kind: "note",
      sensitivity: "public",
      title: "审计范围与入口梳理",
      content: "入口：/login, /orders, /admin\n重点：参数拼接进原始 SQL 的位置。",
      tags: ["scope"],
      vault_ref: "",
      severity: "info",
      status: "open",
      created_at: new Date(Date.now() - 20 * 60_000).toISOString(),
      updated_at: new Date(Date.now() - 20 * 60_000).toISOString(),
      source_session_id: "session-mock",
      source_run_id: "session-mock",
      media_type: "text/plain",
      size_bytes: 72,
    },
    {
      id: "art_secret_1",
      engagement_id: "eng-mock",
      producer: "recon",
      kind: "evidence",
      sensitivity: "secret",
      title: "抓取到的会话凭据样本",
      content: "",
      tags: ["credential"],
      vault_ref: "secret://vault/eng-mock/cred-sample",
      severity: "critical",
      status: "open",
      created_at: new Date(Date.now() - 30 * 60_000).toISOString(),
      updated_at: new Date(Date.now() - 30 * 60_000).toISOString(),
      source_session_id: "session-mock",
      source_run_id: "session-mock",
      media_type: "text/plain",
      size_bytes: 128,
    },
  ],
};

const streams = new Map<string, ReturnType<typeof setTimeout>[]>();

let seq = 1;
let runEventSeq = 100;
const uid = (p: string) => `${p}_${(seq++).toString(36)}${Math.random().toString(36).slice(2, 6)}`;

async function delay<T>(v: T, ms = 120): Promise<T> {
  return new Promise((r) => setTimeout(() => r(v), ms));
}

/** 生成一棵可信的 phase 树（root agent + 规划 / 检索 / 数据流 / 综合）。 */
function buildPhaseTree(sessionId: string, title: string, tail: PhaseSnapshotRow["status"]): PhaseSnapshotRow[] {
  const now = Date.now();
  const at = (i: number) => new Date(now - (6 - i) * 4000).toISOString();
  const row = (
    id: string,
    label: string,
    status: PhaseSnapshotRow["status"],
    parent_id: string | undefined,
    i: number,
  ): PhaseSnapshotRow => ({
    id,
    session_id: sessionId,
    parent_id: parent_id ?? null,
    type: parent_id ? "step" : "agent",
    status,
    label,
    payload: { id, label },
    created_at: at(i),
    updated_at: at(i + 1),
  });
  return [
    row("agent", title.slice(0, 24), tail, undefined, 0),
    row("plan", "规划审计路径", "ok", "agent", 1),
    row("recon", "检索 Sink 与入口", "ok", "agent", 2),
    row("java-auditor", "委派 java-auditor", tail === "failed" ? "failed" : "ok", "agent", 3),
    row("synth", "综合结论", tail, "agent", 4),
  ];
}

function mockRunSummaries(limit = 60): RunSummaryWire[] {
  return store.sessions.slice(0, limit).map((session) => {
    const phases = store.phases[session.id] ?? [];
    const status: RunSummaryWire["status"] =
      phases.length === 0
        ? "queued"
        : phases.some((phase) => phase.status === "pending" || phase.status === "running")
          ? "running"
          : phases.some((phase) => phase.status === "failed")
            ? "failed"
            : "completed";
    const startedAt = phases[0]?.created_at ?? null;
    const finishedAt = status === "running" || status === "queued" ? null : (phases.at(-1)?.updated_at ?? null);
    const durationMs = startedAt
      ? Math.max(0, new Date(finishedAt ?? Date.now()).getTime() - new Date(startedAt).getTime())
      : null;
    return {
      ...session,
      status,
      steps: phases.length,
      started_at: startedAt,
      finished_at: finishedAt,
      duration_ms: durationMs,
    };
  });
}

function buildRunHistory(): RunEventWire[] {
  const createdAt = new Date(Date.now() - 5 * 60_000).toISOString();
  return [
    {
      seq: 1,
      event: "tool_call",
      data: { type: "tool_call", role: "worker", tool: "ripgrep", inputs: { pattern: "execute\\(" }, task_id: "agent" },
      created_at: createdAt,
    },
    {
      seq: 2,
      event: "tool_result",
      data: { type: "tool_result", role: "worker", tool: "ripgrep", ok: true, output: "命中 37 处可疑点", task_id: "agent" },
      created_at: createdAt,
    },
    {
      seq: 3,
      event: "usage",
      data: { type: "usage", model: "claude-mock", turn_input: 4200, turn_output: 620, turn_cost_usd: 0.021, session_input: 82400, session_output: 12900, session_cost_usd: 0.38 },
      created_at: createdAt,
    },
    { seq: 4, event: "done", data: { type: "done" }, created_at: createdAt },
  ];
}

export async function mockInvoke<C extends keyof IpcContract>(
  cmd: C,
  args: IpcContract[C]["args"],
): Promise<IpcContract[C]["result"]> {
  const a = args as Record<string, unknown> | undefined;

  switch (cmd) {
    case "connection_list":
      return delay(store.connections.slice()) as never;

    case "connection_save": {
      const input = (a?.input ?? {}) as {
        id?: string;
        label: string;
        baseUrl: string;
        tlsPolicy?: "system" | "custom_ca";
        caCertPath?: string;
      };
      const existing = input.id ? store.connections.find((c) => c.id === input.id) : undefined;
      const tlsPolicy = input.tlsPolicy ?? "system";
      const profile: ConnectionProfile = {
        id: existing?.id ?? uid("conn"),
        label: input.label,
        baseUrl: input.baseUrl.replace(/\/+$/, ""),
        tlsPolicy,
        caCertPath: tlsPolicy === "custom_ca" ? input.caCertPath : undefined,
        lastConnectedAt: existing?.lastConnectedAt,
        lastKnownVersion: existing?.lastKnownVersion,
      };
      store.connections = [...store.connections.filter((c) => c.id !== profile.id), profile];
      return delay(profile) as never;
    }

    case "connection_delete": {
      const id = a?.id as string;
      store.connections = store.connections.filter((c) => c.id !== id);
      store.authed.delete(id);
      return delay(undefined) as never;
    }

    case "connection_test":
      return delay({
        ok: true,
        serverVersion: "mock-0.0.0",
        workerModel: "claude-mock",
        capabilities: MOCK_CAPS,
        latencyMs: 12,
      }) as never;

    case "connection_activate": {
      const id = a?.id as string;
      return delay({
        connectionId: id,
        status: store.authed.has(id) ? "online" : "unauthenticated",
        auth: { authenticated: store.authed.has(id) },
        health: { ok: true, serverVersion: "mock-0.0.0", capabilities: MOCK_CAPS },
      }) as never;
    }

    case "auth_login": {
      const id = a?.connectionId as string;
      store.authed.add(id);
      return delay({
        authenticated: true,
        expiresAt: new Date(Date.now() + 3600_000).toISOString(),
        userLabel: "mock-user",
      }) as never;
    }

    case "auth_logout": {
      store.authed.delete(a?.connectionId as string);
      return delay(undefined) as never;
    }

    case "api_request": {
      const operation = a?.operation as
        | { op?: string; sessionId?: string; artifactId?: string; afterSeq?: number; limit?: number; kind?: string; callId?: string; approved?: boolean }
        | undefined;
      if (operation?.op === "sessions.list") return delay(store.sessions.slice()) as never;
      if (operation?.op === "runs.list") return delay(mockRunSummaries(operation.limit)) as never;
      if (operation?.op === "sessions.messages") {
        return delay(store.messages[operation.sessionId ?? ""]?.slice() ?? []) as never;
      }
      if (operation?.op === "sessions.phases") {
        return delay(store.phases[operation.sessionId ?? ""]?.slice() ?? []) as never;
      }
      if (operation?.op === "sessions.events") {
        return delay(
          (store.events[operation.sessionId ?? ""] ?? [])
            .filter((event) => event.seq > (operation.afterSeq ?? 0))
            .slice(0, operation.limit ?? 1000),
        ) as never;
      }
      if (operation?.op === "approvals.list") return delay(store.approvals.slice()) as never;
      if (operation?.op === "approvals.history") {
        return delay(store.decisions.slice()) as never;
      }
      if (operation?.op === "approvals.decide") {
        const target = store.approvals.find((ap) => ap.call_id === operation.callId);
        // resolve 已处理项返回失败，模拟后端幂等（call_id 已失效）。
        if (!target) return delay({ ok: false }) as never;
        store.approvals = store.approvals.filter((ap) => ap.call_id !== operation.callId);
        const decision = operation.approved ? "approved" : "rejected";
        const decisionId = uid("dec");
        const entryHash = Array.from({ length: 8 }, () => Math.random().toString(16).slice(2, 10)).join("");
        store.decisions = [
          {
            decision_id: decisionId,
            call_id: target.call_id,
            tool_name: target.tool_name,
            session_id: target.session_id,
            decision,
            risk: target.risk,
            risk_source: target.risk_source,
            target: target.target,
            scope: target.scope,
            impact: target.impact,
            message: target.message,
            decided_at: new Date().toISOString(),
            entry_hash: entryHash,
          },
          ...store.decisions,
        ];
        return delay({ ok: true, decision_id: decisionId, decision, audit_recorded: true, entry_hash: entryHash }) as never;
      }
      if (operation?.op === "artifacts.list") {
        let rows = operation.kind
          ? store.artifacts.filter((art) => art.kind === operation.kind)
          : store.artifacts;
        if (operation.sessionId) rows = rows.filter((art) => art.source_session_id === operation.sessionId);
        return delay(rows.slice()) as never;
      }
      if (operation?.op === "artifacts.get") {
        return delay(store.artifacts.find((art) => art.id === operation.artifactId) ?? null) as never;
      }
      if (operation?.op === "capabilities.agents") return delay(MOCK_CAPABILITIES.agents.slice()) as never;
      if (operation?.op === "capabilities.skills") return delay(MOCK_CAPABILITIES.skills.slice()) as never;
      if (operation?.op === "capabilities.mcp") return delay(MOCK_CAPABILITIES.mcp.slice()) as never;
      if (operation?.op === "capabilities.knowledge") return delay(MOCK_CAPABILITIES.knowledge.slice()) as never;
      if (operation?.op === "capabilities.containers") return delay(MOCK_CAPABILITIES.containers.slice()) as never;
      return delay({ mock: true, operation }) as never;
    }

    case "stream_stop": {
      const handleId = a?.handleId as string;
      for (const timer of streams.get(handleId) ?? []) clearTimeout(timer);
      streams.delete(handleId);
      return delay(undefined) as never;
    }

    case "app_check_update":
      return delay({ available: false, configured: false }) as never;

    case "diagnostics_export":
      return delay({ path: "(mock)/vanta-diagnostics.json", bytes: 512 }) as never;

    case "artifact_export": {
      const artifact = store.artifacts.find((item) => item.id === a?.artifactId);
      if (!artifact || artifact.sensitivity === "secret" || !artifact.content) {
        return Promise.reject({ kind: "forbidden", message: "该产物不可导出", retryable: false });
      }
      return delay({ path: `(mock)/Vanta Exports/${artifact.title}.md`, bytes: artifact.size_bytes ?? artifact.content.length }) as never;
    }

    default:
      return Promise.reject({
        kind: "desktop",
        message: `mock 未实现命令: ${String(cmd)}（需在 Tauri host 下运行）`,
        retryable: false,
      });
  }
}

export async function mockStartChat(
  args: StartChatArgs,
  onEvent: (packet: StreamPacket) => void,
): Promise<IpcContract["chat_start"]["result"]> {
  const handleId = uid("stream");
  const sessionId = args.sessionId ?? uid("session");
  if (!store.sessions.some((session) => session.id === sessionId)) {
    const now = new Date().toISOString();
    store.sessions.unshift({ id: sessionId, title: args.content.slice(0, 28), created_at: now, updated_at: now });
    store.messages[sessionId] = [];
    store.events[sessionId] = [];
  }
  store.messages[sessionId].push({
    id: uid("message"),
    role: "user",
    content: args.content,
    created_at: new Date().toISOString(),
  });

  const answer = `已完成对「${args.content}」的初步分析：\n\n- 认证面：\`/login\` 未复核 \`role\` 声明，存在越权风险。\n- 注入面：\`orderId\` 参数拼接进原始查询，需 PoC 复核。\n\n建议下一步生成最小 PoC 并在隔离容器验证。`;
  const chunks = answer.match(/[\s\S]{1,6}/g) ?? [answer];
  const timers: ReturnType<typeof setTimeout>[] = [];
  let step = 0;
  const emit = (packet: StreamPacket, gap = 60) => {
    step += 1;
    if (
      packet.event === "tool_call" ||
      packet.event === "tool_result" ||
      packet.event === "tool_error" ||
      packet.event === "worker_start" ||
      packet.event === "worker_end" ||
      packet.event === "usage" ||
      packet.event === "phase" ||
      packet.event === "task_log" ||
      packet.event === "done"
    ) {
      const history = store.events[sessionId] ?? (store.events[sessionId] = []);
      history.push({
        seq: runEventSeq++,
        event: packet.event,
        data: packet.data as Record<string, unknown>,
        created_at: new Date().toISOString(),
      });
    }
    timers.push(setTimeout(() => onEvent(packet), step * gap));
  };

  emit({ event: "session", data: sessionId });
  emit({ event: "worker_start", data: { type: "worker_start", worker: "agent", instruction: args.content.slice(0, 80), task_id: "agent" } });
  emit({ event: "phase", data: { type: "phase", id: "agent", label: args.content.slice(0, 24), status: "running", task_id: "agent" } });
  emit({ event: "phase", data: { type: "phase", id: "plan", label: "规划审计路径", status: "running", parent_id: "agent" } });
  emit({ event: "task_log", data: { type: "task_log", task_id: "agent", message: "载入代码审计知识库" } });
  emit({ event: "phase", data: { type: "phase", id: "plan", label: "规划审计路径", status: "ok", parent_id: "agent" } });
  emit({ event: "phase", data: { type: "phase", id: "recon", label: "检索 Sink 与入口", status: "running", parent_id: "agent" } });
  emit({ event: "tool_call", data: { type: "tool_call", role: "worker", tool: "ripgrep", inputs: { pattern: "execute\\(", glob: "*.java" }, task_id: "agent" } });
  emit({ event: "tool_result", data: { type: "tool_result", role: "worker", tool: "ripgrep", ok: true, output: "命中 37 处可疑点", task_id: "agent" } }, 140);
  emit({ event: "phase", data: { type: "phase", id: "recon", label: "检索 Sink 与入口", status: "ok", parent_id: "agent" } });
  emit({ event: "phase", data: { type: "phase", id: "java-auditor", label: "委派 java-auditor", status: "running", parent_id: "agent" } });
  emit({ event: "phase", data: { type: "phase", id: "java-auditor", label: "委派 java-auditor", status: "ok", parent_id: "agent" } });
  emit({ event: "phase", data: { type: "phase", id: "synth", label: "综合结论", status: "running", parent_id: "agent" } });
  chunks.forEach((text) => emit({ event: "text_delta", data: { type: "text_delta", role: "worker", text, task_id: "agent" } }, 28));
  emit({ event: "usage", data: { type: "usage", model: "claude-mock", turn_input: 4200, turn_output: 620, turn_cost_usd: 0.021, session_input: 82_400, session_output: 12_900, session_cost_usd: 0.38 } });
  emit({ event: "phase", data: { type: "phase", id: "synth", label: "综合结论", status: "ok", parent_id: "agent" } });
  emit({ event: "phase", data: { type: "phase", id: "agent", label: args.content.slice(0, 24), status: "ok", task_id: "agent" } });
  emit({ event: "done", data: { type: "done" } });

  timers.push(
    setTimeout(
      () => {
        store.messages[sessionId].push({
          id: uid("message"),
          role: "assistant",
          content: answer,
          created_at: new Date().toISOString(),
        });
        store.phases[sessionId] = buildPhaseTree(sessionId, args.content, "ok");
        const idx = store.sessions.findIndex((s) => s.id === sessionId);
        if (idx >= 0) store.sessions[idx] = { ...store.sessions[idx], updated_at: new Date().toISOString() };
        onEvent({ event: "stream.closed", data: { reason: "completed" } });
        streams.delete(handleId);
      },
      (step + 2) * 60,
    ),
  );
  streams.set(handleId, timers);
  return { handleId, channelId: seq };
}

export async function mockRunSubscribe(
  args: RunSubscribeArgs,
  onEvent: (packet: StreamPacket) => void,
): Promise<IpcContract["run_subscribe"]["result"]> {
  const handleId = uid("runsub");
  const rows = store.phases[args.runId] ?? [];
  const timers: ReturnType<typeof setTimeout>[] = [];
  timers.push(setTimeout(() => onEvent({ event: "snapshot", data: { phases: rows.slice(), seq: 1 } }), 60));
  timers.push(
    setTimeout(() => {
      onEvent({ event: "stream.closed", data: { reason: "completed" } });
      streams.delete(handleId);
    }, 140),
  );
  streams.set(handleId, timers);
  return { handleId, channelId: seq };
}
