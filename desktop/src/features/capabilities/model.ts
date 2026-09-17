/**
 * 能力目录 view model 与归一化（Plan G4）。
 *
 * 桌面端只呈现后端已声明或注册的能力，可用状态必须来自运行时事实，
 * 不伪装可用（规范 §4.5 / §7）。各来源的 wire 形状与后端逐字段对齐：
 * - agent    ← GET /v1/agents      （harness/routes/agents.py _list_agents）
 * - skill    ← GET /v1/skills      （harness/routes/skills.py _list_skills）
 * - mcp      ← GET /v1/mcp/servers （harness/routes/mcp.py MCPServerView）
 * - knowledge← GET /v1/knowledge   （harness/routes/_utils.py knowledge_to_dict）
 * - runtime  ← GET /v1/containers  （harness/routes/_utils.py container_to_dict）
 */

import { Boxes, BookOpen, Cpu, Plug, Wrench, type LucideIcon } from "lucide-react";
import type { Tone } from "@/components/desktop/status";
import type { ContainerWire } from "@/contracts/containers";
import type { AgentWire } from "@/contracts/agents";
import type { SkillWire } from "@/contracts/skills";
import type { McpServerWire } from "@/contracts/mcp";

export type CapabilityKind = "agent" | "skill" | "mcp" | "knowledge" | "runtime";

export const CAPABILITY_KIND: Record<CapabilityKind, { label: string; icon: LucideIcon }> = {
  agent: { label: "Agent", icon: Boxes },
  skill: { label: "Skill", icon: Wrench },
  mcp: { label: "MCP", icon: Plug },
  knowledge: { label: "知识库", icon: BookOpen },
  runtime: { label: "执行环境", icon: Cpu },
};

export type Availability = "available" | "discovered" | "unavailable" | "needs_config";

export const AVAILABILITY: Record<Availability, { label: string; tone: Tone }> = {
  available: { label: "可用", tone: "ok" },
  discovered: { label: "已发现", tone: "accent" },
  needs_config: { label: "需配置", tone: "warn" },
  unavailable: { label: "不可用", tone: "danger" },
};

export type CapabilityItem = {
  id: string;
  kind: CapabilityKind;
  name: string;
  /** 来源分组标签：内置 / 工作区 / MCP 服务 / 向量库分类 / 容器。 */
  source: string;
  availability: Availability;
  detail: string;
  dependency?: string;
  /** 运行位置：本机 / 后端 / 容器。 */
  location?: string;
};

// ─── wire 形状（与后端逐字段对齐） ─────────────────────────────────────

export type KnowledgeWire = {
  id: string;
  name: string;
  title?: string;
  category?: string;
  content?: string;
  tags?: string[];
};

// ─── 归一化：wire → CapabilityItem（可用性来自运行时事实） ──────────────

/** Agent 来自后端目录扫描：已注册即后端可调度。 */
export function agentToItem(a: AgentWire): CapabilityItem {
  const dep = [a.model, a.provider ?? undefined].filter(Boolean).join(" · ");
  const invocation = a.disable_model_invocation ? "仅按名调用" : "模型可自动选择";
  return {
    id: `agent:${a.id}`,
    kind: "agent",
    name: a.name || a.id,
    source: "Agent 目录",
    availability: "available",
    detail: `${invocation} · ${a.description || "已注册的编排 Agent"}`,
    dependency: dep || undefined,
    location: "后端",
  };
}

/** Skill 来自后端目录扫描：已注册即可按需加载。 */
export function skillToItem(s: SkillWire): CapabilityItem {
  return {
    id: `skill:${s.id}`,
    kind: "skill",
    name: s.name || s.id,
    source: "Skill 目录",
    availability: "available",
    detail: s.description || "按需加载的 Skill",
    dependency: s.model || (s.allowed_tools.length ? `${s.allowed_tools.length} 个工具` : undefined),
    location: "后端",
  };
}

/** MCP 可用性取自 manager 运行时握手状态，不按配置存在即宣称可用。 */
export function mcpToItem(m: McpServerWire): CapabilityItem {
  const status = m.status ?? "disconnected";
  let availability: Availability;
  let detail: string;
  if (m.enabled === false) {
    availability = "needs_config";
    detail = "已配置但未启用";
  } else if (status === "connected") {
    availability = "available";
    detail = `已连接 · ${m.tool_count ?? 0} 个工具`;
  } else if (status === "error") {
    availability = "unavailable";
    detail = m.error ? `连接失败：${m.error}` : "连接失败";
  } else {
    availability = "discovered";
    detail = "已配置，尚未完成连接";
  }
  return {
    id: `mcp:${m.name}`,
    kind: "mcp",
    name: m.name,
    source: "MCP 目录",
    availability,
    detail,
    dependency: m.command || undefined,
    location: "本机",
  };
}

/** 知识条目按 category 分组；已入库即后端可检索。 */
export function knowledgeToItem(k: KnowledgeWire): CapabilityItem {
  const category = k.category || "未分类";
  return {
    id: `knowledge:${k.id}`,
    kind: "knowledge",
    name: k.title || k.name || k.id,
    source: `知识 目录`,
    availability: "available",
    detail: (k.tags && k.tags.length ? k.tags.join(" / ") : category),
    location: "后端",
  };
}

/** 执行环境可用性取自 podman live 状态（daemon 不可达时后端退回 store 静态状态）。 */
export function containerToItem(c: ContainerWire): CapabilityItem {
  const status = (c.status ?? "").toLowerCase();
  let availability: Availability;
  let detail: string;
  if (status === "running") {
    availability = "available";
    detail = "运行中的隔离容器";
  } else if (status === "exited" || status === "stopped" || status === "created" || status === "paused") {
    availability = "needs_config";
    detail = `容器${status === "created" ? "已创建，未启动" : "已停止，需启动"}`;
  } else if (status === "dead" || status === "error") {
    availability = "unavailable";
    detail = "容器异常，不可用";
  } else {
    availability = "discovered";
    detail = status ? `状态：${status}` : "已登记的执行环境";
  }
  return {
    id: `runtime:${c.id}`,
    kind: "runtime",
    name: c.name || c.id,
    source: "容器 目录",
    availability,
    detail,
    dependency: c.image || undefined,
    location: "容器",
  };
}
