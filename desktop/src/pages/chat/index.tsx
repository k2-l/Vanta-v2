import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { Activity, CheckCircle2, Minimize2, Pencil, Plus, RotateCw, Trash2, X } from "lucide-react";
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
import type { ChatMessage, CompressPreview, SessionSummary } from "@/contracts/chat";
import { toClientError } from "@/contracts/errors";
import { ipc } from "@/ipc/client";
import { cn } from "@/lib/cn";
import { startChat } from "@/ipc/chat";
import { useConnection } from "@/stores/connection";
import { useUi } from "@/stores/ui";
import { NEW_CHAT_EVENT } from "@/hooks/useHotkeys";
import { formatRelative } from "@/lib/format";
import { applyPacket, emptyProjection, type RunProjection } from "@/features/runs/projection";
import { RunDetailBody } from "@/features/runs/RunDetail";
import { useRunProjection } from "@/features/runs/useRuns";
import { StepList } from "@/features/chat/StepList";
import { CompressionDialog } from "@/features/chat/CompressionDialog";
import { InlineApprovals } from "@/features/chat/InlineApprovals";
import { useIsModuleActive, useModuleNavigation } from "@/app/moduleNavigation";

export function ChatPage() {
  const connectionId = useConnection((state) => state.activeConnectionId);
  const authenticated = useConnection((state) => state.auth.authenticated);
  const eventReplay = useConnection((state) => state.capabilities.eventReplay);
  const runHistory = useConnection((state) => state.capabilities.runHistory);
  const selectStore = useUi((s) => s.select);
  const navigate = useNavigate();
  const openModule = useModuleNavigation();
  const moduleActive = useIsModuleActive("chat");
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
  const [compressionPreview, setCompressionPreview] = useState<(CompressPreview & { sessionId: string }) | null>(null);
  const [compressionSummary, setCompressionSummary] = useState("");
  const [compressionNotice, setCompressionNotice] = useState<string>();
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
    if (streaming || compressPreview.isPending || compressCommit.isPending) return;
    setSelectedId(undefined);
    setNewChat(true);
    resetLive();
  };

  const selectSession = (id: string) => {
    if (streaming || compressPreview.isPending || compressCommit.isPending) return;
    setSelectedId(id);
    setNewChat(false);
    resetLive();
  };

  const sessionsKey = ["sessions", connectionId] as const;

  const renameSession = useMutation<unknown, unknown, { id: string; title: string }>({
    mutationFn: (v) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "sessions.patch", sessionId: v.id, title: v.title },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sessionsKey }),
    onError: (cause) => setError(toClientError(cause).message),
  });

  const deleteSession = useMutation<unknown, unknown, string>({
    mutationFn: (id) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "sessions.delete", sessionId: id },
      }),
    onSuccess: (_result, id) => {
      // 先在缓存中摘除，再据剩余项决定选中，避免落到已删会话触发 messages 404。
      const remaining = (queryClient.getQueryData<SessionSummary[]>(sessionsKey) ?? []).filter(
        (s) => s.id !== id,
      );
      queryClient.setQueryData<SessionSummary[]>(sessionsKey, remaining);
      queryClient.removeQueries({ queryKey: ["messages", connectionId, id] });
      queryClient.removeQueries({ queryKey: ["phases", connectionId, id] });
      if (selectedId === id) {
        const next = remaining[0]?.id;
        setSelectedId(next);
        setNewChat(!next);
        resetLive();
      }
      queryClient.invalidateQueries({ queryKey: sessionsKey });
    },
    onError: (cause) => setError(toClientError(cause).message),
  });

  const compressPreview = useMutation<CompressPreview, unknown, string>({
    mutationFn: async (sessionId) => {
      const result = await ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "sessions.compress.preview", sessionId },
      });
      return result as CompressPreview;
    },
    onMutate: () => {
      setError(undefined);
      setCompressionNotice(undefined);
    },
    onSuccess: (preview, sessionId) => {
      setCompressionPreview({ ...preview, sessionId });
      setCompressionSummary(preview.summary);
    },
    onError: (cause) => setError(toClientError(cause).message),
  });

  const compressCommit = useMutation<unknown, unknown, { sessionId: string; summary: string; upto: string }>({
    mutationFn: (input) =>
      ipc("api_request", {
        connectionId: connectionId!,
        operation: {
          op: "sessions.compress.commit",
          sessionId: input.sessionId,
          summary: input.summary,
          upto: input.upto,
        },
      }),
    onSuccess: async () => {
      const messages = compressionPreview?.messages ?? 0;
      const before = compressionPreview?.tokens_before ?? 0;
      const after = compressionPreview?.tokens_after ?? 0;
      setCompressionPreview(null);
      setCompressionSummary("");
      setCompressionNotice(`已压缩 ${messages} 条消息，估算上下文 ${before} → ${after} tokens`);
      if (selectedId) {
        await queryClient.invalidateQueries({ queryKey: ["budget", connectionId, selectedId] });
      }
    },
    onError: (cause) => setError(toClientError(cause).message),
  });

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
  } = useRunProjection(streaming ? undefined : selectedId, moduleActive);
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
  const compressionBusy = compressPreview.isPending || compressCommit.isPending;
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
                <SessionRow
                  key={session.id}
                  session={session}
                  selected={selectedId === session.id}
                  disabled={streaming || compressionBusy}
                  deleting={deleteSession.isPending}
                  onSelect={() => selectSession(session.id)}
                  onRename={(title) => renameSession.mutate({ id: session.id, title })}
                  onDelete={() => deleteSession.mutate(session.id)}
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
    openModule("runs", { selectedId, detailOpen: true });
  };

  const detail = (
    <DetailPanel title="运行详情" onClose={() => useUi.getState().setDetailOpen("chat", false)}>
      {detailProjection && detailProjection.phaseOrder.length > 0 ? (
        <>
          <RunDetailBody projection={detailProjection} eventReplay={eventReplay} runHistory={runHistory} />
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
            <InlineApprovals sessionId={selectedId} streaming={streaming} />
            {compressionNotice && (
              <div
                className="mx-auto mb-2 flex max-w-3xl items-center gap-2 rounded-[var(--radius)] border px-3 py-2 text-[12px]"
                style={{ borderColor: "var(--ok)", background: "var(--ok-tint)", color: "var(--fg)" }}
              >
                <CheckCircle2 size={14} style={{ color: "var(--ok)" }} />
                <span className="flex-1">{compressionNotice}</span>
                <button aria-label="关闭提示" onClick={() => setCompressionNotice(undefined)} style={{ color: "var(--fg-muted)" }}>
                  <X size={14} />
                </button>
              </div>
            )}
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
              footer={
                <Button
                  size="xs"
                  variant="ghost"
                  disabled={
                    streaming ||
                    compressionBusy ||
                    !selectedId ||
                    history.isLoading ||
                    !history.data?.length
                  }
                  title={!selectedId ? "请先选择一个已有会话" : "生成可编辑摘要后再确认应用"}
                  onClick={() => selectedId && compressPreview.mutate(selectedId)}
                >
                  <Minimize2 size={13} />
                  {compressPreview.isPending ? "正在生成压缩预览…" : "压缩上下文"}
                </Button>
              }
            />
            <CompressionDialog
              preview={compressionPreview}
              summary={compressionSummary}
              pending={compressCommit.isPending}
              onSummaryChange={setCompressionSummary}
              onClose={() => {
                setCompressionPreview(null);
                setCompressionSummary("");
              }}
              onCommit={() => {
                if (!compressionPreview || !compressionSummary.trim()) return;
                compressCommit.mutate({
                  sessionId: compressionPreview.sessionId,
                  summary: compressionSummary.trim(),
                  upto: compressionPreview.upto,
                });
              }}
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

function IconAction({
  label,
  danger = false,
  disabled = false,
  onClick,
  children,
}: {
  label: string;
  danger?: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="grid h-6 w-6 place-items-center rounded-[var(--radius-sm)] border transition-colors hover:bg-[var(--surface-inset)] disabled:opacity-40"
      style={{ color: danger ? "var(--danger)" : "var(--fg-muted)", background: "var(--surface-overlay)", borderColor: "var(--border)" }}
    >
      {children}
    </button>
  );
}

/**
 * 会话行：常态展示标题 + 时间，悬停或选中时显示重命名 / 删除操作。
 * 操作层是 ResourceRow（按钮）的兄弟元素而非子元素，避免按钮嵌套并阻止点击冒泡到选中。
 * 重命名切换为内联输入（Enter/失焦保存、Esc 取消）；删除需内联二次确认。
 */
function SessionRow({
  session,
  selected,
  disabled,
  deleting,
  onSelect,
  onRename,
  onDelete,
}: {
  session: SessionSummary;
  selected: boolean;
  disabled: boolean;
  deleting: boolean;
  onSelect: () => void;
  onRename: (title: string) => void;
  onDelete: () => void;
}) {
  const [mode, setMode] = useState<"idle" | "rename" | "confirm">("idle");
  const [draft, setDraft] = useState(session.title || "");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (mode === "rename") {
      setDraft(session.title || "");
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [mode, session.title]);

  const commit = () => {
    const next = draft.trim();
    setMode("idle");
    if (next && next !== (session.title || "")) onRename(next);
  };

  if (mode === "rename") {
    return (
      <div className="px-1 py-1">
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commit();
            } else if (e.key === "Escape") {
              e.preventDefault();
              setMode("idle");
            }
          }}
          onBlur={commit}
          maxLength={200}
          aria-label="重命名会话"
          className="w-full rounded-[var(--radius)] border px-2 py-1.5 text-[13px] outline-none"
          style={{ background: "var(--surface-inset)", borderColor: "var(--accent)", color: "var(--fg)" }}
        />
      </div>
    );
  }

  if (mode === "confirm") {
    return (
      <div
        className="flex items-center gap-2 rounded-[var(--radius)] px-2 py-2"
        style={{ background: "var(--danger-tint)" }}
      >
        <span className="min-w-0 flex-1 truncate text-[12px]" style={{ color: "var(--fg)" }}>
          删除「{session.title || "新会话"}」？
        </span>
        <Button
          size="xs"
          variant="danger"
          disabled={deleting}
          onClick={() => {
            setMode("idle");
            onDelete();
          }}
        >
          删除
        </Button>
        <Button size="xs" variant="ghost" onClick={() => setMode("idle")}>
          取消
        </Button>
      </div>
    );
  }

  return (
    <div className="group/row relative">
      <ResourceRow
        dense
        selected={selected}
        title={session.title || "新会话"}
        meta={formatRelative(session.updated_at)}
        onClick={onSelect}
      />
      <div
        className={cn(
          // 隐藏时置 pointer-events-none，避免透明操作层拦截行右侧的选中点击。
          "absolute right-1.5 top-1/2 flex -translate-y-1/2 items-center gap-1 opacity-0 transition-opacity",
          "pointer-events-none group-hover/row:pointer-events-auto focus-within:pointer-events-auto",
          "group-hover/row:opacity-100 focus-within:opacity-100",
          selected && "pointer-events-auto opacity-100",
        )}
      >
        <IconAction label="重命名" disabled={disabled} onClick={() => setMode("rename")}>
          <Pencil size={13} />
        </IconAction>
        <IconAction label="删除" danger disabled={disabled} onClick={() => setMode("confirm")}>
          <Trash2 size={13} />
        </IconAction>
      </div>
    </div>
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
