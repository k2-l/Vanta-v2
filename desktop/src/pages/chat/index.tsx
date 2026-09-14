import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Send, Square } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/Button";
import { EmptyState } from "@/components/EmptyState";
import type { ChatMessage, ChatStreamPacket, SessionSummary } from "@/contracts/chat";
import { toClientError } from "@/contracts/errors";
import { ipc } from "@/ipc/client";
import { startChat } from "@/ipc/chat";
import { useConnection } from "@/stores/connection";

type LiveTurn = { sessionId?: string; user: string; assistant: string };

export function ChatPage() {
  const connectionId = useConnection((state) => state.activeConnectionId);
  const authenticated = useConnection((state) => state.auth.authenticated);
  const [selectedId, setSelectedId] = useState<string>();
  const [newChat, setNewChat] = useState(false);
  const [draft, setDraft] = useState("");
  const [live, setLive] = useState<LiveTurn | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string>();
  const handleRef = useRef<string>();
  const bottomRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const sessions = useQuery<SessionSummary[]>({
    queryKey: ["sessions", connectionId],
    enabled: Boolean(connectionId && authenticated),
    queryFn: async () => {
      const result = await ipc("api_request", {
        connectionId: connectionId!, operation: { op: "sessions.list", limit: 100 },
      });
      return Array.isArray(result) ? result as SessionSummary[] : [];
    },
  });

  useEffect(() => {
    if (!selectedId && !newChat && sessions.data?.length) setSelectedId(sessions.data[0].id);
  }, [newChat, selectedId, sessions.data]);

  const history = useQuery<ChatMessage[]>({
    queryKey: ["messages", connectionId, selectedId],
    // 新会话收到 session 帧时先展示本地 live turn，避免立即拉历史造成用户消息重复。
    enabled: Boolean(connectionId && authenticated && selectedId && !streaming),
    queryFn: async () => {
      const result = await ipc("api_request", {
        connectionId: connectionId!,
        operation: { op: "sessions.messages", sessionId: selectedId!, limit: 200 },
      });
      return Array.isArray(result) ? result as ChatMessage[] : [];
    },
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: streaming ? "smooth" : "auto" });
  }, [history.data, live?.assistant, streaming]);

  if (!connectionId || !authenticated) {
    return (
      <div className="grid h-full place-items-center p-8">
        <EmptyState title="连接后开始对话" hint="请先在设置中激活服务器并登录。凭据只保存在本机 Rust Core。" />
      </div>
    );
  }

  const finish = async (sessionId?: string) => {
    setStreaming(false);
    handleRef.current = undefined;
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["sessions", connectionId] }),
      sessionId
        ? queryClient.invalidateQueries({ queryKey: ["messages", connectionId, sessionId] })
        : Promise.resolve(),
    ]);
    setLive(null);
  };

  const onPacket = (packet: ChatStreamPacket, getSessionId: () => string | undefined) => {
    if (packet.event === "session" && typeof packet.data === "string") {
      setSelectedId(packet.data);
      setNewChat(false);
      setLive((turn) => turn ? { ...turn, sessionId: packet.data as string } : turn);
      return;
    }
    if (packet.event === "text_delta") {
      const text = readTextDelta(packet.data);
      if (text) setLive((turn) => turn ? { ...turn, assistant: turn.assistant + text } : turn);
      return;
    }
    if (packet.event === "client_error") {
      setError(toClientError(packet.data).message);
      void finish(getSessionId());
      return;
    }
    if (packet.event === "stream.closed") void finish(getSessionId());
  };

  const send = async () => {
    const content = draft.trim();
    if (!content || streaming) return;
    setDraft("");
    setError(undefined);
    setStreaming(true);
    setLive({ sessionId: selectedId, user: content, assistant: "" });
    let runSessionId = selectedId;
    try {
      const handle = await startChat(
        {
          connectionId,
          sessionId: selectedId,
          content,
          clientRequestId: crypto.randomUUID(),
        },
        (packet) => {
          if (packet.event === "session" && typeof packet.data === "string") runSessionId = packet.data;
          onPacket(packet, () => runSessionId);
        },
      );
      handleRef.current = handle.handleId;
    } catch (cause) {
      setError(toClientError(cause).message);
      setStreaming(false);
      setLive(null);
    }
  };

  const stop = async () => {
    const handleId = handleRef.current;
    if (handleId) {
      await ipc("stream_stop", { handleId });
      await finish(live?.sessionId ?? selectedId);
    }
  };

  const shownLive = live && (!live.sessionId || live.sessionId === selectedId) ? live : null;

  return (
    <div className="grid h-full grid-cols-[250px_minmax(0,1fr)]">
      <aside className="flex min-h-0 flex-col border-r" style={{ borderColor: "var(--border)", background: "var(--bg-elevated)" }}>
        <div className="flex h-14 items-center justify-between border-b px-3" style={{ borderColor: "var(--border)" }}>
          <strong className="text-sm">会话</strong>
          <Button
            size="sm" variant="ghost" aria-label="新建对话" disabled={streaming}
            onClick={() => { setSelectedId(undefined); setNewChat(true); setLive(null); setError(undefined); }}
          >
            <Plus size={16} />
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {sessions.isLoading && <p className="p-2 text-xs text-[var(--fg-muted)]">加载中…</p>}
          {sessions.data?.map((session) => (
            <button
              key={session.id}
              className="mb-1 w-full rounded-md px-3 py-2 text-left"
              style={{
                background: selectedId === session.id ? "var(--bg-inset)" : "transparent",
                color: selectedId === session.id ? "var(--fg)" : "var(--fg-muted)",
              }}
              onClick={() => { if (!streaming) { setSelectedId(session.id); setNewChat(false); setLive(null); setError(undefined); } }}
            >
              <span className="block truncate text-sm">{session.title || "新会话"}</span>
              <span className="block text-[11px] text-[var(--fg-subtle)]">{formatDate(session.updated_at)}</span>
            </button>
          ))}
        </div>
      </aside>

      <section className="flex min-w-0 flex-col">
        <header className="flex h-14 shrink-0 items-center border-b px-5" style={{ borderColor: "var(--border)" }}>
          <h1 className="truncate font-semibold">
            {sessions.data?.find((session) => session.id === selectedId)?.title ?? "新对话"}
          </h1>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {!history.isLoading && !(history.data?.length) && !shownLive && (
            <div className="grid h-full place-items-center">
              <EmptyState title="开始一段新对话" hint="消息将由本机 Rust Core 安全转发到当前服务器。" />
            </div>
          )}
          <div className="mx-auto flex max-w-3xl flex-col gap-5">
            {history.data?.map((message) => <MessageBubble key={message.id} message={message} />)}
            {shownLive && (
              <>
                <MessageBubble message={{ id: "live-user", role: "user", content: shownLive.user, created_at: "" }} />
                <MessageBubble
                  message={{ id: "live-assistant", role: "assistant", content: shownLive.assistant || "思考中…", created_at: "" }}
                  muted={!shownLive.assistant}
                />
              </>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="shrink-0 px-6 pb-5">
          <div className="mx-auto max-w-3xl">
            {error && <p className="mb-2 text-xs text-[var(--danger)]">{error}</p>}
            <div className="flex items-end gap-2 rounded-xl border bg-[var(--bg-elevated)] p-2" style={{ borderColor: "var(--border)" }}>
              <textarea
                value={draft} rows={1} placeholder="输入消息…"
                className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none"
                disabled={streaming}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void send();
                  }
                }}
              />
              {streaming ? (
                <Button size="sm" variant="secondary" onClick={() => void stop()}><Square size={14} />停止</Button>
              ) : (
                <Button size="sm" disabled={!draft.trim()} onClick={() => void send()}><Send size={15} />发送</Button>
              )}
            </div>
            <p className="mt-2 text-center text-[11px] text-[var(--fg-subtle)]">Enter 发送 · Shift + Enter 换行</p>
          </div>
        </div>
      </section>
    </div>
  );
}

function MessageBubble({ message, muted = false }: { message: ChatMessage; muted?: boolean }) {
  const user = message.role === "user";
  return (
    <article className={user ? "ml-auto max-w-[80%] rounded-xl bg-[var(--accent)] px-4 py-3 text-[var(--accent-fg)]" : "mr-auto max-w-full px-1 py-1"}>
      {user ? <p className="whitespace-pre-wrap">{message.content}</p> : (
        <div className={muted ? "text-[var(--fg-subtle)]" : "chat-markdown"}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
        </div>
      )}
    </article>
  );
}

function readTextDelta(data: unknown): string {
  if (!data || typeof data !== "object") return "";
  const text = (data as { text?: unknown }).text;
  return typeof text === "string" ? text : "";
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}
