/**
 * 能力目录数据层（Plan G4）——并行拉取五类来源，归一化为 CapabilityItem。
 *
 * 单来源失败不清空整页：用 allSettled 收集，成功的照常呈现，失败的记入
 * `failed`，页面据此给出降级提示；五类全部失败才视为整页错误（规范 §7）。
 * 此 hook 只负责目录读取；容器写侧和生命周期由 features/containers 独立封装。
 */

import { useQuery } from "@tanstack/react-query";
import { ipc } from "@/ipc/client";
import { useConnection } from "@/stores/connection";
import type { ApiOperation } from "@/contracts/ipc";
import type { ContainerWire } from "@/contracts/containers";
import type { AgentWire } from "@/contracts/agents";
import type { SkillWire } from "@/contracts/skills";
import type { McpServerWire } from "@/contracts/mcp";
import {
  agentToItem,
  containerToItem,
  knowledgeToItem,
  mcpToItem,
  skillToItem,
  type CapabilityItem,
  type CapabilityKind,
  type KnowledgeWire,
} from "./model";

type CatalogResult = {
  items: CapabilityItem[];
  agents: AgentWire[];
  skills: SkillWire[];
  mcpServers: McpServerWire[];
  containers: ContainerWire[];
  /** 拉取失败的来源类别（部分降级时非空）。 */
  failed: CapabilityKind[];
};

type Source<W> = {
  kind: CapabilityKind;
  op: ApiOperation;
  map: (row: W) => CapabilityItem;
};

const SOURCES: [
  Source<AgentWire>,
  Source<SkillWire>,
  Source<McpServerWire>,
  Source<KnowledgeWire>,
  Source<ContainerWire>,
] = [
  { kind: "agent", op: { op: "capabilities.agents" }, map: agentToItem },
  { kind: "skill", op: { op: "capabilities.skills" }, map: skillToItem },
  { kind: "mcp", op: { op: "capabilities.mcp" }, map: mcpToItem },
  { kind: "knowledge", op: { op: "capabilities.knowledge" }, map: knowledgeToItem },
  { kind: "runtime", op: { op: "capabilities.containers" }, map: containerToItem },
];

export function useCapabilities() {
  const connectionId = useConnection((s) => s.activeConnectionId);
  const authed = useConnection((s) => s.auth.authenticated);
  return useQuery<CatalogResult>({
    queryKey: ["capabilities", connectionId],
    enabled: Boolean(connectionId && authed),
    staleTime: 20_000,
    queryFn: async () => {
      const settled = await Promise.allSettled(
        SOURCES.map((s) => ipc("api_request", { connectionId: connectionId!, operation: s.op })),
      );
      const items: CapabilityItem[] = [];
      let agents: AgentWire[] = [];
      let skills: SkillWire[] = [];
      let mcpServers: McpServerWire[] = [];
      let containers: ContainerWire[] = [];
      const failed: CapabilityKind[] = [];
      settled.forEach((res, i) => {
        const src = SOURCES[i];
        if (res.status === "fulfilled" && Array.isArray(res.value)) {
          if (src.kind === "agent") agents = res.value as AgentWire[];
          if (src.kind === "skill") skills = res.value as SkillWire[];
          if (src.kind === "mcp") mcpServers = res.value as McpServerWire[];
          if (src.kind === "runtime") containers = res.value as ContainerWire[];
          for (const row of res.value) items.push(src.map(row as never));
        } else {
          failed.push(src.kind);
        }
      });
      // 五类全部失败：抛出让页面进入错误态，而不是显示空目录。
      if (failed.length === SOURCES.length) {
        const first = settled.find((r) => r.status === "rejected");
        throw first && first.status === "rejected" ? first.reason : new Error("能力目录加载失败");
      }
      return { items, agents, skills, mcpServers, containers, failed };
    },
  });
}
