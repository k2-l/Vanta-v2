/**
 * 浏览器开发用 mock IPC——仅在无 Tauri host 时启用。
 *
 * 目的：让前端在 `npm run dev`（普通浏览器）下可独立开发与走查 UI，
 * 不代表真实后端行为，也绝不持有真实凭据。连接/凭据数据仅存内存。
 */

import { DEFAULT_CAPABILITIES } from "@/contracts/connection";
import type { ConnectionProfile } from "@/contracts/connection";
import type { ChatMessage, ChatStreamPacket, SessionSummary } from "@/contracts/chat";
import type { IpcContract } from "@/contracts/ipc";
import type { StartChatArgs } from "./chat";

const store: {
  connections: ConnectionProfile[];
  authed: Set<string>;
  sessions: SessionSummary[];
  messages: Record<string, ChatMessage[]>;
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
      title: "欢迎使用 Vanta",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  ],
  messages: {
    "session-mock": [
      {
        id: "message-mock",
        role: "assistant",
        content: "这是浏览器 mock 会话。连接真实 Tauri Core 后，消息会由后端流式返回。",
        created_at: new Date().toISOString(),
      },
    ],
  },
};

const streams = new Map<string, ReturnType<typeof setTimeout>[]>();

let seq = 1;
const uid = (p: string) => `${p}_${(seq++).toString(36)}${Math.random().toString(36).slice(2, 6)}`;

async function delay<T>(v: T, ms = 120): Promise<T> {
  return new Promise((r) => setTimeout(() => r(v), ms));
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
      const input = (a?.input ?? {}) as { id?: string; label: string; baseUrl: string; tlsPolicy?: "system" | "custom_ca" };
      const existing = input.id ? store.connections.find((c) => c.id === input.id) : undefined;
      const profile: ConnectionProfile = {
        id: existing?.id ?? uid("conn"),
        label: input.label,
        baseUrl: input.baseUrl.replace(/\/+$/, ""),
        tlsPolicy: input.tlsPolicy ?? "system",
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
        capabilities: DEFAULT_CAPABILITIES,
        latencyMs: 12,
      }) as never;

    case "connection_activate": {
      const id = a?.id as string;
      return delay({
        connectionId: id,
        status: store.authed.has(id) ? "online" : "unauthenticated",
        auth: { authenticated: store.authed.has(id) },
        health: { ok: true, serverVersion: "mock-0.0.0", capabilities: DEFAULT_CAPABILITIES },
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
      const operation = a?.operation as { op?: string; sessionId?: string } | undefined;
      if (operation?.op === "sessions.list") return delay(store.sessions.slice()) as never;
      if (operation?.op === "sessions.messages") {
        return delay(store.messages[operation.sessionId ?? ""]?.slice() ?? []) as never;
      }
      return delay({ mock: true, operation }) as never;
    }

    case "stream_stop": {
      const handleId = a?.handleId as string;
      for (const timer of streams.get(handleId) ?? []) clearTimeout(timer);
      streams.delete(handleId);
      return delay(undefined) as never;
    }

    case "app_check_update":
      return delay({ available: false }) as never;

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
  onEvent: (packet: ChatStreamPacket) => void,
): Promise<IpcContract["chat_start"]["result"]> {
  const handleId = uid("stream");
  const sessionId = args.sessionId ?? uid("session");
  if (!store.sessions.some((session) => session.id === sessionId)) {
    const now = new Date().toISOString();
    store.sessions.unshift({ id: sessionId, title: args.content.slice(0, 28), created_at: now, updated_at: now });
    store.messages[sessionId] = [];
  }
  store.messages[sessionId].push({
    id: uid("message"), role: "user", content: args.content, created_at: new Date().toISOString(),
  });

  const answer = `收到：${args.content}\n\n这是一段由浏览器 mock 生成的流式回复。`;
  const chunks = answer.match(/.{1,5}/gs) ?? [answer];
  const timers: ReturnType<typeof setTimeout>[] = [];
  const emit = (packet: ChatStreamPacket, index: number) => {
    timers.push(setTimeout(() => onEvent(packet), index * 45));
  };
  emit({ event: "session", data: sessionId }, 1);
  chunks.forEach((text, index) => emit(
    { event: "text_delta", data: { type: "text_delta", text } }, index + 2,
  ));
  emit({ event: "done", data: { type: "done" } }, chunks.length + 2);
  timers.push(setTimeout(() => {
    store.messages[sessionId].push({
      id: uid("message"), role: "assistant", content: answer, created_at: new Date().toISOString(),
    });
    onEvent({ event: "stream.closed", data: { reason: "completed" } });
    streams.delete(handleId);
  }, (chunks.length + 3) * 45));
  streams.set(handleId, timers);
  return { handleId, channelId: seq };
}
