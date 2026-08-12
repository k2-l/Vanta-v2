/**
 * Harness API 客户端（非流式）。
 * 流式聊天见 lib/sse.ts
 *
 * 所有受保护路由都自动带 Authorization；401 时调 forceLogout。
 */

import { authHeader, useAuth } from "@/store/auth";

// 本地开发：设置 VITE_API_BASE=http://127.0.0.1:8765（在 web/.env）
// Docker/nginx 同域代理：留空，请求通过 window.location.origin 走 nginx
export const API_BASE = (import.meta.env.VITE_API_BASE as string) || "";

export type Session = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type Message = {
  id: string;
  role: string;
  content: string;
  created_at: string;
};

export type MemoryItem = {
  id: string;
  text: string;
  metadata: Record<string, unknown>;
  distance?: number | null;
};

async function http<T>(
  path: string,
  init?: RequestInit & { params?: Record<string, string | number> }
): Promise<T> {
  // 本地开发时 VITE_API_BASE 应显式配置；
  // Docker/nginx 时为空 → 用 window.location.origin 走同域 nginx 代理；
  // 开发模式未配置时 fallback 到 127.0.0.1:8765
  const base = API_BASE || window.location.origin;
  const url = new URL(base + path);
  if (init?.params) {
    for (const [k, v] of Object.entries(init.params)) {
      url.searchParams.set(k, String(v));
    }
  }
  const resp = await fetch(url.toString(), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeader(),
      ...(init?.headers || {}),
    },
  });
  if (resp.status === 401) {
    useAuth.getState().forceLogout("登录已失效，请重新登录");
    throw new Error("401 Unauthorized");
  }
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`${resp.status} ${resp.statusText}${text ? `: ${text}` : ""}`);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

export const api = {
  base: API_BASE,

  health: () => http<{ status: string; version: string; worker_model: string }>("/health"),
  me: () => http<{ authenticated: boolean; expires_at: string | null }>("/auth/me"),

  // ---- sessions ----
  listSessions: (limit = 50) =>
    http<Session[]>("/sessions", { params: { limit } }),

  createSession: (title = "新会话") =>
    http<Session>("/sessions", {
      method: "POST",
      body: JSON.stringify({ title }),
    }),

  getMessages: (sessionId: string, limit = 200) =>
    http<Message[]>(`/sessions/${sessionId}/messages`, { params: { limit } }),

  deleteSession: (sessionId: string) =>
    http<{ ok: boolean }>(`/sessions/${sessionId}`, { method: "DELETE" }),

  patchSession: (sessionId: string, title: string) =>
    http<Session>(`/sessions/${sessionId}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),

  // ---- approvals (HITL, item 6) ----
  submitApproval: (callId: string, approved: boolean) =>
    http<{ ok: boolean }>(`/chat/approvals/${callId}`, {
      method: "POST",
      body: JSON.stringify({ approved }),
    }),

  // ---- memory ----
  remember: (text: string, sessionId?: string) =>
    http<{ id: string }>("/memory/remember", {
      method: "POST",
      body: JSON.stringify({ text, session_id: sessionId, role: "user" }),
    }),

  memoryList: (sessionId: string, limit = 50) =>
    http<MemoryItem[]>("/memory/list", { params: { session_id: sessionId, limit } }),

  memorySearch: (query: string, k = 5) =>
    http<MemoryItem[]>("/memory/search", {
      method: "POST",
      body: JSON.stringify({ query, k }),
    }),

  memoryClear: (sessionId: string) =>
    http<{ deleted: number }>("/memory/clear", {
      method: "DELETE",
      params: { session_id: sessionId },
    }),

  // ---- suite: skills ----
  listSkills: async () => {
    // harness /v1/skills 返回 allowed_tools / triggers 已是数组；patterns/contexts/priority 未序列化，前端补空
    const raw = await http<Omit<SuiteSkill, "patterns" | "contexts" | "priority">[]>("/v1/skills");
    return raw.map((s): SuiteSkill => ({ ...s, patterns: [], contexts: [], priority: 0 }));
  },
  registerSkill: (md: string) =>
    http<SuiteSkill>("/v1/skills/register", { method: "POST", body: JSON.stringify({ md }) }),
  updateSkill: (id: string, patch: Partial<SuiteSkill>) =>
    http<SuiteSkill>(`/v1/skills/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteSkill: (id: string) =>
    http<void>(`/v1/skills/${id}`, { method: "DELETE" }),
  scanSkills: () =>
    http<{ registered: number; skipped: number }>("/v1/skills/scan", { method: "POST" }),

  // ---- suite: agents ----
  listAgents: () => http<SuiteAgent[]>("/v1/agents"),
  registerAgent: (md: string) =>
    http<SuiteAgent>("/v1/agents/register", { method: "POST", body: JSON.stringify({ md }) }),
  updateAgent: (id: string, patch: Partial<SuiteAgent>) =>
    http<SuiteAgent>(`/v1/agents/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteAgent: (id: string) =>
    http<void>(`/v1/agents/${id}`, { method: "DELETE" }),
  scanAgents: () =>
    http<{ registered: number; skipped: number }>("/v1/agents/scan", { method: "POST" }),

  // ---- suite: knowledge ----
  listKnowledge: async (category?: string) => {
    const all = await http<KnowledgeEntry[]>("/v1/knowledge");
    return category ? all.filter((k) => k.category === category) : all;
  },
  registerKnowledge: (entry: Omit<KnowledgeEntry, "id">) =>
    http<KnowledgeEntry>("/v1/knowledge/register", { method: "POST", body: JSON.stringify(entry) }),
  updateKnowledge: (id: string, patch: Partial<KnowledgeEntry>) =>
    http<KnowledgeEntry>(`/v1/knowledge/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteKnowledge: (id: string) =>
    http<void>(`/v1/knowledge/${id}`, { method: "DELETE" }),
  scanKnowledge: () =>
    http<{ registered: number; skipped: number }>("/v1/workspace/sync/knowledge", { method: "POST" }),

  // ---- tools ----
  listTools: () => http<{ name: string; category: string }[]>("/v1/tools"),

  // ---- workspace ----
  workspace: () => http<{ workspace_dir: string | null; configured: boolean }>("/v1/workspace"),

  // ---- token budget ----
  budget: (sessionId: string) => http<BudgetStatus>(`/budget/${sessionId}`),

  // ---- runtime config ----
  getConfig: () => http<Record<string, unknown>>("/config"),
  patchConfig: (updates: Record<string, unknown>) =>
    http<{ status: string; updated: string[] }>("/config", {
      method: "PATCH",
      body: JSON.stringify({ updates }),
    }),

  // ---- profile ----
  getProfile: () => http<{ content: string }>("/profile"),
  putProfile: (content: string) => http<{ content: string }>("/profile", {
    method: "PUT", body: JSON.stringify({ content }),
  }),

  // ---- containers（harness :8765，podman 直连）----
  listContainers: () => http<Container[]>("/v1/containers"),
  createContainer: (data: Omit<Container, "id" | "status" | "container_id" | "created_at" | "updated_at">) =>
    http<Container>("/v1/containers", { method: "POST", body: JSON.stringify(data) }),
  startContainer: (id: string) =>
    http<Container>(`/v1/containers/${id}/start`, { method: "PATCH" }),
  stopContainer: (id: string) =>
    http<Container>(`/v1/containers/${id}/stop`, { method: "PATCH" }),
  deleteContainer: (id: string) =>
    http<void>(`/v1/containers/${id}`, { method: "DELETE" }),

  // ---- board / artifacts（只读；写侧仅 agent 的 board 工具）----
  listArtifacts: (filter?: { engagement_id?: string; kind?: string }) => {
    const params: Record<string, string> = {};
    if (filter?.engagement_id) params.engagement_id = filter.engagement_id;
    if (filter?.kind) params.kind = filter.kind;
    return http<Artifact[]>("/v1/artifacts", { params });
  },

  // ---- MCP servers ----
  listMcpServers: () => http<McpServer[]>("/v1/mcp/servers"),
  getMcpServer: (name: string) => http<McpServer>(`/v1/mcp/servers/${encodeURIComponent(name)}`),
  createMcpServer: (data: {
    name: string; command: string; args?: string[]; env?: Record<string, string>;
    enabled?: boolean; confirm: boolean;
  }) =>
    http<McpServer>("/v1/mcp/servers", { method: "POST", body: JSON.stringify(data) }),
  deleteMcpServer: (name: string, confirm: boolean) =>
    http<{ status: string; name: string; removed_tools: string[] }>(`/v1/mcp/servers/${encodeURIComponent(name)}`, {
      method: "DELETE",
      body: JSON.stringify({ confirm }),
    }),
  testMcpServer: (name: string) =>
    http<{ ok: boolean; error: string | null; tools: string[] }>(`/v1/mcp/servers/${encodeURIComponent(name)}/test`, {
      method: "POST",
    }),

};

export type Container = {
  id: string;
  name: string;
  image: string;
  status: "created" | "running" | "stopped";
  ports: string[];
  env_vars: string[];
  container_id: string;
  managed?: boolean;        // false = 外部容器（非本 App 创建），只读展示
  created_at?: string;
  updated_at?: string;
};

export type Artifact = {
  id: string;
  engagement_id: string | null;
  producer: string;
  kind: string;            // finding / scan_result / recon / report / note
  sensitivity: string;     // public / internal / secret
  title: string;
  content: string;         // secret 类不回明文（见后端 artifact_to_dict）
  tags: string[];
  vault_ref: string;
  severity: string | null; // 仅 kind=finding 有意义
  status: string;
  created_at: string | null;
};

export type McpTool = {
  name: string;          // 本地注册名：mcp__<server>__<tool>
  remote_name: string;   // 远端原名
};

export type McpServer = {
  name: string;
  command: string;
  args: string[];
  enabled: boolean;
  env_keys: string[];                                  // 脱敏：只回 key 名，不回明文 value
  status: "connected" | "disconnected" | "error";
  error: string | null;
  tool_count: number;
  tools: McpTool[];      // 列表接口为空数组，详情接口才填充
};

export type BudgetStatus = {
  session: { used: number; limit: number; percent: number };
  daily:   { used: number; limit: number; percent: number };
  context_window: number;
  summary_trigger: number;
};

export type KnowledgeEntry = {
  id: string;
  name: string;
  title: string;
  category: string;
  content: string;
  tags: string[];
  created_at?: string;
  updated_at?: string;
};

export type SuiteSkill = {
  id: string;
  name: string;
  description: string;
  content: string;
  allowed_tools: string[];
  model: string | null;
  effort: string | null;
  context: string | null;
  argument_hint: string | null;
  version: string | null;
  triggers: string[];
  patterns: string[];
  contexts: string[];
  priority: number;
  active: boolean;
  created_at?: string;
  updated_at?: string;
};

export type SuiteAgent = {
  id: string;
  name: string;
  description: string;
  content: string;
  tools: string[];
  model: string | null;
  active: boolean;
  max_tokens: number;
  temperature: number;
  allow_autonomous: boolean;
  enable_critic: boolean;
  type?: string;
  status?: string;
  dependencies?: string[];
  created_at?: string;
  updated_at?: string;
};
