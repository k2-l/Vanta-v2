/**
 * 浏览器开发用 mock IPC——仅在无 Tauri host 时启用。
 *
 * 目的：让前端在 `npm run dev`（普通浏览器）下可独立开发与走查 UI，
 * 不代表真实后端行为，也绝不持有真实凭据。连接/凭据数据仅存内存。
 */

import { DEFAULT_CAPABILITIES } from "@/contracts/connection";
import type { ConnectionProfile } from "@/contracts/connection";
import type { IpcContract } from "@/contracts/ipc";

const store: {
  connections: ConnectionProfile[];
  authed: Set<string>;
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
};

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

    case "api_request":
      return delay({ mock: true, operation: a?.operation }) as never;

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
