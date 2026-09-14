/**
 * 能力模块静态骨架数据（Plan G1.5）。G4 起改由后端能力目录驱动；
 * 桌面端只呈现后端已声明的能力，不伪装可用（规范 §4.5 / §7）。
 */

import { Boxes, BookOpen, Cpu, Plug, Wrench, type LucideIcon } from "lucide-react";
import type { Tone } from "@/components/desktop/status";

export type CapabilityKind = "agent" | "skill" | "mcp" | "knowledge" | "runtime";

export const CAPABILITY_KIND: Record<CapabilityKind, { label: string; icon: LucideIcon }> = {
  agent: { label: "Agent", icon: Boxes },
  skill: { label: "技能", icon: Wrench },
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
  /** 来源：内置 / 工作区 / 远程服务器 / MCP 服务名。 */
  source: string;
  availability: Availability;
  detail: string;
  dependency?: string;
  /** 运行位置：本机 / 后端 / 容器。 */
  location?: string;
  lastSync?: string;
};

const now = Date.now();
const ago = (mins: number) => new Date(now - mins * 60_000).toISOString();

export const CAPABILITY_ITEMS: CapabilityItem[] = [
  {
    id: "cap_orch",
    kind: "agent",
    name: "orchestrator",
    source: "后端 · 内置",
    availability: "available",
    detail: "统一安全测试调度器，路由白盒 / 黑盒 / 灰盒",
    location: "后端",
    lastSync: ago(2),
  },
  {
    id: "cap_audit",
    kind: "agent",
    name: "audit-analyst",
    source: "后端 · 内置",
    availability: "available",
    detail: "白盒深度分析：数据流追踪与可利用性判定",
    location: "后端",
    lastSync: ago(2),
  },
  {
    id: "cap_pentest",
    kind: "agent",
    name: "pentest-analyst",
    source: "后端 · 内置",
    availability: "available",
    detail: "黑盒 / 灰盒渗透，从侦察到后渗透",
    location: "后端",
    lastSync: ago(2),
  },
  {
    id: "cap_sqlmap",
    kind: "skill",
    name: "sqlmap-runner",
    source: "工作区 · skills/",
    availability: "needs_config",
    detail: "需要在设置中声明容器执行环境后启用",
    dependency: "执行环境：隔离容器",
    location: "容器",
    lastSync: ago(30),
  },
  {
    id: "cap_recon",
    kind: "skill",
    name: "passive-recon",
    source: "工作区 · skills/",
    availability: "available",
    detail: "被动资产收集与指纹归并",
    location: "后端",
    lastSync: ago(30),
  },
  {
    id: "cap_mcp_fs",
    kind: "mcp",
    name: "filesystem",
    source: "MCP · stdio",
    availability: "available",
    detail: "受控文件读写（工作区范围内）",
    dependency: "@modelcontextprotocol/server-filesystem",
    location: "本机",
    lastSync: ago(8),
  },
  {
    id: "cap_mcp_http",
    kind: "mcp",
    name: "http-probe",
    source: "MCP · stdio",
    availability: "discovered",
    detail: "已发现但尚未握手完成能力协商",
    location: "本机",
    lastSync: ago(8),
  },
  {
    id: "cap_kb",
    kind: "knowledge",
    name: "evolved-web-vulns",
    source: "向量库 · Qdrant Cloud",
    availability: "available",
    detail: "Web 漏洞经验库（蒸馏后模式）",
    location: "后端",
    lastSync: ago(60),
  },
  {
    id: "cap_kb_infra",
    kind: "knowledge",
    name: "evolved-ad-attacks",
    source: "向量库 · Qdrant Cloud",
    availability: "unavailable",
    detail: "向量集合未同步；后端未声明该集合",
    location: "后端",
    lastSync: ago(600),
  },
  {
    id: "cap_container",
    kind: "runtime",
    name: "podman · isolated",
    source: "后端 · 容器",
    availability: "needs_config",
    detail: "egress 锁定沙箱；需在连接中确认容器可用",
    dependency: "podman ≥ 4.0",
    location: "容器",
    lastSync: ago(15),
  },
];
