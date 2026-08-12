import { useState, useEffect } from "react";
import { NavSidebar } from "@/app/NavSidebar";
import { MessageList } from "@/features/chat/components/MessageList";
import { ChatInput } from "@/features/chat/components/ChatInput";
import { TasksPanel } from "@/features/chat/components/TasksPanel";
import { LoginPage } from "@/app/LoginPage";
import { ErrorBoundary } from "@/shared/components/ErrorBoundary";
import { ModuleHeader, ModuleTitle } from "@/shared/components/ModuleHeader";
import { AgentPage } from "@/features/agents/AgentPage";
import { SkillPage } from "@/features/skills/SkillPage";
import { KbPage } from "@/features/knowledge/KbPage";
import { ContainerPage } from "@/features/containers/ContainerPage";
import { ConfigPage } from "@/features/config/ConfigPage";
import { MemoryPage } from "@/features/memory/MemoryPage";
import { McpPage } from "@/features/mcp/McpPage";
import { useAuth } from "@/store/auth";
import { useChat } from "@/store/chat";
import { useSessionWs } from "@/shared/lib/ws";

export type Module = "chat" | "agent" | "skill" | "kb" | "memory" | "container" | "mcp" | "config";

const MODULES: Module[] = ["chat", "agent", "skill", "kb", "memory", "container", "mcp", "config"];
const ACTIVE_MODULE_KEY = "harness.activeModule";

// 各 page 的 wrapper：只渲染一次，切换时用 display 控制显隐
// 避免 key={activeModule} 导致每次切换都卸载/重挂载，重复触发 load()
function PageSlot({
  active,
  children,
}: {
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        flex: 1,
        display: active ? "flex" : "none",
        overflow: "hidden",
        minWidth: 0,
      }}
    >
      {children}
    </div>
  );
}

export default function App() {
  const token = useAuth((s) => s.token);
  const expiresAt = useAuth((s) => s.expiresAt);
  // 持久化当前 tab：刷新页面后保持在同一模块，而非每次弹回 chat
  const [activeModule, setActiveModule] = useState<Module>(() => {
    const saved = localStorage.getItem(ACTIVE_MODULE_KEY) as Module | null;
    return saved && MODULES.includes(saved) ? saved : "chat";
  });
  const currentSessionId = useChat((s) => s.currentSessionId);
  useSessionWs(activeModule === "chat" ? currentSessionId : null);

  useEffect(() => {
    localStorage.setItem(ACTIVE_MODULE_KEY, activeModule);
  }, [activeModule]);

  const authed =
    !!token && !!expiresAt && new Date(expiresAt).getTime() > Date.now();

  if (!authed) return <LoginPage />;

  return (
    <div
      style={{
        display: "flex",
        height: "100vh",
        width: "100vw",
        background: "#F4F5F7",
        color: "#1A1D23",
        fontFamily: "'SF Mono','JetBrains Mono','Fira Code',monospace",
        overflow: "hidden",
      }}
    >
      <NavSidebar activeModule={activeModule} onModuleChange={setActiveModule} />

      <div style={{ flex: 1, display: "flex", overflow: "hidden", minWidth: 0, position: "relative" }}>
        {/* chat — always rendered, shown when active */}
        <PageSlot active={activeModule === "chat"}>
          <ErrorBoundary>
            <div style={{ flex: 1, display: "flex", overflow: "hidden", position: "relative" }}>
              <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" }}>
                <ModuleHeader title={<ModuleTitle>对话</ModuleTitle>} />
                <MessageList />
                <ChatInput />
              </div>
              <TasksPanel />
            </div>
          </ErrorBoundary>
        </PageSlot>

        {/* management pages — mounted on first visit, kept alive after */}
        <PageSlot active={activeModule === "agent"}>
          <ErrorBoundary>
            <AgentPage />
          </ErrorBoundary>
        </PageSlot>

        <PageSlot active={activeModule === "skill"}>
          <ErrorBoundary>
            <SkillPage />
          </ErrorBoundary>
        </PageSlot>

        <PageSlot active={activeModule === "kb"}>
          <ErrorBoundary>
            <KbPage />
          </ErrorBoundary>
        </PageSlot>

        <PageSlot active={activeModule === "memory"}>
          <ErrorBoundary>
            <MemoryPage />
          </ErrorBoundary>
        </PageSlot>

        <PageSlot active={activeModule === "container"}>
          <ErrorBoundary>
            <ContainerPage />
          </ErrorBoundary>
        </PageSlot>

        <PageSlot active={activeModule === "mcp"}>
          <ErrorBoundary>
            <McpPage />
          </ErrorBoundary>
        </PageSlot>

        <PageSlot active={activeModule === "config"}>
          <ErrorBoundary>
            <ConfigPage />
          </ErrorBoundary>
        </PageSlot>
      </div>
    </div>
  );
}
