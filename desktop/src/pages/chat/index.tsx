import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { Activity, Plus, RotateCw, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/Button";
import {
  ModuleLayout,
  ContextRail,
  RailSearch,
  RailGroupLabel,
  ContentHeader,
  DetailToggleButton,
  DetailPanel,
  ResourceList,
  ResourceRow,
  DesktopComposer,
  StatusDot,
  EmptyState,
  LoadingState,
  ErrorState,
} from "@/components/desktop";
import type { ChatMessage, SessionSummary } from "@/contracts/chat";
import { toClientError } from "@/contracts/errors";
import { ipc } from "@/ipc/client";
import { startChat } from "@/ipc/chat";
import { useConnection } from "@/stores/connection";
import { useUi } from "@/stores/ui";
import { NEW_CHAT_EVENT } from "@/hooks/useHotkeys";
import { formatRelative } from "@/lib/format";
import { applyPacket, emptyProjection, type RunProjection } from "@/features/runs/projection";
import { RunDetailBody } from "@/features/runs/RunDetail";
import { useRunProjection } from "@/features/runs/useRuns";
import { StepList } from "@/features/chat/StepList";

export function ChatPage() {
  const connectionId = useConnection((state) => state.activeConnectionId);
  const authenticated = useConnection((state) => state.auth.authenticated);
  const eventReplay = useConnection((state) => state.capabilities.eventReplay);
  const selectStore = useUi((s) => s.select);
  const navigate = useNavigate();
  const location = useLocation();
  const [selectedId, setSelectedIdLocal] = useState<string | undefined>(
    () => useUi.getState().modules.chat.selectedId ?? undefined,
  );
  const [newChat, setNewChat] = useState(false);
  const [draft, setDraft] = useState("");
  const [search, setSearch] = useState("");
  const [liveUser, setLiveUser] = useState<string | null>(null);
  const [projection, setProjection] = useState<RunProjection | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string>();
  const lastSentRef = useRef<string>("");
  const handleRef = useRef<string>();
  const bottomRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const setSelectedId = (id?: string) => {
    setSelectedIdLocal(id);
    selectStore("chat", id ?? null);
  };

  const resetLive = () => {
    setLiveUser(null);
    setProjection(null);
    setError(undefined);
  };

  const sessions = useQuery<SessionSummary[]>({
    queryKey: ["sessions", connectionId],
    enabled: Boolean(connectionId && authenticated),
    queryFn: async () => {
      const result = await ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "sessions.list", limit: 100 },
      });
      return Array.isArray(result) ? (result as SessionSummary[]) : [];
    },
  });

  useEffect(() => {
    if (!selectedId && !newChat && sessions.data?.length) setSelectedId(sessions.data[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [newChat, selectedId, sessions.data]);

  const startNewChat = () => {
    if (streaming) return;
    setSelectedId(undefined);
    setNewChat(true);
    resetLive();
  };

  const selectSession = (id: string) => {
    if (streaming) return;
    setSelectedId(id);
    setNewChat(false);
    resetLive();
  };

  useEffect(() => {
    const onNew = () => startNewChat();
    window.addEventListener(NEW_CHAT_EVENT, onNew);
    return () => window.removeEventListener(NEW_CHAT_EVENT, onNew);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streaming]);

  // 卸载时（含连接切换触发的整体重挂载）停止在途流，避免 Rust 侧订阅泄漏（G4 连接隔离）。
  useEffect(() => {
    return () => {
      const handleId = handleRef.current;
      if (handleId) void ipc("stream_stop", { handleId });
    };
  }, []);

  useEffect(() => {
    const state = location.state as { newChat?: boolean } | null;
    if (!state?.newChat) return;
    startNewChat();
    navigate(location.pathname, { replace: true, state: null });
    // 只消费本次路由 state；startNewChat 随 streaming 变化不应重复触发。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key]);

  const history = useQuery<ChatMessage[]>({
    queryKey: ["messages", connectionId, selectedId],
    enabled: Boolean(connectionId && authenticated && selectedId && !streaming),
    queryFn: async () => {
      const result = await ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "sessions.messages", sessionId: selectedId!, limit: 200 },
      });
      return Array.isArray(result) ? (result as ChatMessage[]) : [];
    },
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: streaming ? "smooth" : "auto" });
  }, [history.data, projection?.assistant, streaming]);

  const groups = useMemo(() => groupSessions(sessions.data ?? [], search), [sessions.data, search]);
  const activeSession = sessions.data?.find((s) => s.id === selectedId);
  const liveMatches = projection && (!projection.sessionId || projection.sessionId === selectedId);
  const {
    projection: storedProjection,
    isLoading: storedRunLoading,
    isError: storedRunError,
    error: storedRunErrorMessage,
    refetch: refetchStoredRun,
  } = useRunProjection(streaming ? undefined : selectedId);
  const detailProjection = liveMatches && projection?.phaseOrder.length ? projection : storedProjection;

  const finish = async (sessionId?: string) => {
    setStreaming(false);
    handleRef.current = undefined;
    setLiveUser(null); // 用户与助手消息改由 history 呈现；projection 保留用于步骤/用量。
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["sessions", connectionId] }),
      sessionId ? queryClient.invalidateQueries({ queryKey: ["messages", connectionId, sessionId] }) : Promise.resolve(),
      sessionId ? queryClient.invalidateQueries({ queryKey: ["phases", connectionId, sessionId] }) : Promise.resolve(),
    ]);
  };

  const send = async (content: string) => {
    const trimmed = content.trim();
    if (!trimmed || streaming) return;
    setDraft("");
    setError(undefined);
    setStreaming(true);
    setLiveUser(trimmed);
    lastSentRef.current = trimmed;
    setProjection(emptyProjection(selectedId));
    let runSessionId = selectedId;
    try {
      const handle = await startChat(
        { connectionId: connectionId!, sessionId: selectedId, content: trimmed, clientRequestId: crypto.randomUUID() },
        (packet) => {
          if (packet.event === "session" && typeof packet.data === "string") {
            runSessionId = packet.data;
            setSelectedId(packet.data);
            setNewChat(false);
          }
          if (packet.event === "client_error") setError(toClientError(packet.data).message);
          setProjection((p) => applyPacket(p ?? emptyProjection(runSessionId), packet));
          if (packet.event === "stream.closed") void finish(runSessionId);
        },
      );
      handleRef.current = handle.handleId;
    } catch (cause) {
      setError(toClientError(cause).message);
      setStreaming(false);
      setProjection((p) => (p ? { ...p, status: "failed" } : p));
    }
  };

  const stop = async () => {
    const handleId = handleRef.current;
    if (handleId) {
      await ipc("stream_stop", { handleId });
      await finish(projection?.sessionId ?? selectedId);
    }
  };

  const connected = Boolean(connectionId && authenticated);
  const showRunSummary = !streaming && liveMatches && projection && projection.phaseOrder.length > 0;

  const rail = (
    <ContextRail
      title="对话"
      action={
        <Button size="icon" variant="ghost" aria-label="新建对话" disabled={streaming || !connected} onClick={startNewChat}>
          <Plus size={16} />
        </Button>
      }
      search={connected ? <RailSearch value={search} onChange={setSearch} placeholder="搜索会话… (⌘K)" /> : undefined}
    >
      {!connected ? (
        <p className="px-2 py-3 text-[12px]" style={{ color: "var(--fg-subtle)" }}>连接并登录后可见会话。</p>
      ) : sessions.isLoading ? (
        <p className="px-2 py-3 text-[12px]" style={{ color: "var(--fg-muted)" }}>加载中…</p>
      ) : groups.length === 0 ? (
        <p className="px-2 py-3 text-[12px]" style={{ color: "var(--fg-subtle)" }}>
          {search ? "无匹配会话" : "还没有会话，点右上角新建。"}
        </p>
      ) : (
        groups.map((group) => (
          <div key={group.label}>
            <RailGroupLabel>{group.label}</RailGroupLabel>
            <ResourceList>
              {group.items.map((session) => (
                <ResourceRow
                  key={session.id}
                  dense
                  selected={selectedId === session.id}
                  title={session.title || "新会话"}
                  meta={formatRelative(session.updated_at)}
                  onClick={() => selectSession(session.id)}
                />
              ))}
            </ResourceList>
          </div>
        ))
      )}
    </ContextRail>
  );

  const openInRuns = () => {
    if (!selectedId) return;
    useUi.getState().select("runs", selectedId);
    useUi.getState().setDetailOpen("runs", true);
    navigate("/runs");
  };

  const detail = (
    <DetailPanel title="运行详情" onClose={() => useUi.getState().setDetailOpen("chat", false)}>
      {detailProjection && detailProjection.phaseOrder.length > 0 ? (
        <>
          <RunDetailBody projection={detailProjection} eventReplay={eventReplay} />
          <Button size="sm" variant="secondary" className="mt-1 w-full" onClick={openInRuns}>
            <Activity size={14} />
            在运行页打开
          </Button>
        </>
      ) : storedRunLoading ? (
        <LoadingState title="加载运行快照…" />
      ) : storedRunError ? (
        <ErrorState
          title="运行详情加载失败"
          hint={storedRunErrorMessage}
          action={<Button size="xs" variant="secondary" onClick={() => void refetchStoredRun()}>重新加载</Button>}
        />
      ) : (
        <EmptyState title="暂无运行详情" hint="发送消息后，这里展示 Run ID、状态、阶段树、用量与关联产物。" />
      )}
    </DetailPanel>
  );

  return (
    <ModuleLayout module="chat" rail={rail} detail={detail}>
      <ContentHeader
        title={newChat ? "新对话" : (activeSession?.title ?? "对话")}
        subtitle={connected ? "消息由本机 Rust Core 安全转发到当前服务器" : undefined}
        leading={streaming ? <StatusDot tone="running" /> : undefined}
        actions={<DetailToggleButton module="chat" />}
      />

      {!connected ? (
        <EmptyState title="连接后开始对话" hint="请先在设置中激活服务器并登录。凭据只保存在本机 Rust Core。" />
      ) : (
        <>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
            {!history.isLoading && !history.data?.length && !liveUser && !showRunSummary && (
              <EmptyState title="开始一段新对话" hint="消息将由本机 Rust Core 安全转发到当前服务器。" />
            )}
            <div className="mx-auto flex max-w-3xl flex-col gap-5">
              {history.data?.map((message) => <MessageBubble key={message.id} message={message} />)}

              {streaming && liveUser && (
                <>
                  <MessageBubble message={{ id: "live-user", role: "user", content: liveUser, created_at: "" }} />
                  {projection && projection.phaseOrder.length > 0 && <StepList projection={projection} />}
                  {projection?.assistant ? (
                    <MessageBubble
                      message={{ id: "live-assistant", role: "assistant", content: projection.assistant, created_at: "" }}
                      streaming
                    />
                  ) : (
                    <div className="flex items-center gap-2 text-[12px]" style={{ color: "var(--fg-muted)" }}>
                      <StatusDot tone="running" /> 思考中…
                    </div>
                  )}
                </>
              )}

              {showRunSummary && projection && <StepList projection={projection} />}
              <div ref={bottomRef} />
            </div>
          </div>

          <div className="shrink-0 px-6 pb-5">
            {error && (
              <div
                className="mx-auto mb-2 flex max-w-3xl items-center gap-3 rounded-[var(--radius)] border px-3 py-2"
                style={{ borderColor: "var(--danger)", background: "var(--danger-tint)" }}
              >
                <span className="flex-1 text-[12px]" style={{ color: "var(--fg)" }}>{error}</span>
                <Button size="xs" variant="secondary" disabled={streaming} onClick={() => void send(lastSentRef.current)}>
                  <RotateCw size={13} /> 重试
                </Button>
                <button aria-label="关闭错误" onClick={() => setError(undefined)} style={{ color: "var(--fg-muted)" }}>
                  <X size={14} />
                </button>
              </div>
            )}
            <DesktopComposer
              value={draft}
              onChange={setDraft}
              onSend={() => void send(draft)}
              onStop={() => void stop()}
              streaming={streaming}
            />
          </div>
        </>
      )}
    </ModuleLayout>
  );
}

function MessageBubble({ message, streaming = false }: { message: ChatMessage; streaming?: boolean }) {
  if (message.role === "user") {
    return (
      <article
        className="ml-auto max-w-[80%] select-text rounded-[var(--radius-lg)] px-3.5 py-2.5 text-[13px]"
        style={{ background: "var(--surface-inset)", color: "var(--fg)" }}
      >
        <p className="whitespace-pre-wrap">{message.content}</p>
      </article>
    );
  }
  return (
    <article className="mr-auto max-w-full select-text px-1">
      <div className={streaming ? "chat-markdown vanta-caret" : "chat-markdown"} style={{ color: "var(--fg)" }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
      </div>
    </article>
  );
}

type SessionGroup = { label: string; items: SessionSummary[] };

function groupSessions(sessions: SessionSummary[], search: string): SessionGroup[] {
  const q = search.trim().toLowerCase();
  const filtered = q ? sessions.filter((s) => (s.title || "").toLowerCase().includes(q)) : sessions;
  const now = Date.now();
  const buckets: Record<string, SessionSummary[]> = { 今天: [], 昨天: [], "最近 7 天": [], 更早: [] };
  for (const s of filtered) {
    const days = Math.floor((now - new Date(s.updated_at).getTime()) / 86_400_000);
    const key = days <= 0 ? "今天" : days === 1 ? "昨天" : days <= 7 ? "最近 7 天" : "更早";
    (buckets[key] ?? buckets["更早"]).push(s);
  }
  return Object.entries(buckets)
    .filter(([, items]) => items.length > 0)
    .map(([label, items]) => ({ label, items }));
}
