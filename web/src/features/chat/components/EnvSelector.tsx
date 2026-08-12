/**
 * EnvSelector — 执行环境选择器（物理机 / 容器）。
 *
 * 挂在 ChatInput HUD 栏，下拉显示 "物理机" 和运行中的容器列表。
 * 选择后写入 chat store executionEnv。
 */

import { useEffect, useState } from "react";
import { api, type Container } from "@/shared/lib/api";
import { useChat } from "@/store/chat";

export function EnvSelector() {
  const executionEnv = useChat((s) => s.executionEnv);
  const setExecutionEnv = useChat((s) => s.setExecutionEnv);
  const [containers, setContainers] = useState<Container[]>([]);

  useEffect(() => {
    api.listContainers()
      // 只列本 App 管理的容器（managed）：外部容器（postgres/harness 等）无 ContainerRecord、无法作执行环境
      .then((cs) => setContainers(cs.filter((c) => c.managed && c.status === "running")))
      .catch(() => setContainers([]));
  }, []);

  return (
    <select
      value={executionEnv}
      onChange={(e) => setExecutionEnv(e.target.value)}
      className="h-6 rounded border border-zinc-600 bg-zinc-800 px-1.5 text-xs text-zinc-300 focus:outline-none focus:ring-1 focus:ring-zinc-500"
      title="执行环境"
    >
      <option value="local">物理机</option>
      {containers.map((c) => (
        <option key={c.id} value={`container:${c.id}`}>
          {c.name}
        </option>
      ))}
    </select>
  );
}
