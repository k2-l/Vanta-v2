/**
 * IPC 命令契约（方案 §8.2）。
 *
 * WebView 只能调用 allowlist 中的 Tauri command；通用 api_request 只接受
 * 受控的 ApiOperation 枚举，绝不接受任意 method + URL。
 */

import type {
  AuthSummary,
  ConnectionDraft,
  ConnectionProfile,
  ConnectionSession,
  HealthResult,
} from "./connection";

/** 命令名 allowlist——与 Rust `#[tauri::command]` 一一对应，也是 TS 侧唯一入口。 */
export const IPC = {
  connectionList: "connection_list",
  connectionSave: "connection_save",
  connectionDelete: "connection_delete",
  connectionTest: "connection_test",
  connectionActivate: "connection_activate",
  authLogin: "auth_login",
  authLogout: "auth_logout",
  apiRequest: "api_request",
  chatStart: "chat_start",
  runSubscribe: "run_subscribe",
  streamStop: "stream_stop",
  artifactExport: "artifact_export",
  diagnosticsExport: "diagnostics_export",
  appCheckUpdate: "app_check_update",
} as const;

export type IpcCommand = (typeof IPC)[keyof typeof IPC];

/**
 * 受控 API 操作枚举（替代任意 method+URL）。
 * G0 只登记只读探活/会话类；资源写操作随各 Gate 增量登记。
 */
export type ApiOperation =
  | { op: "health" }
  | { op: "me" }
  | { op: "sessions.list"; limit?: number }
  | { op: "sessions.create"; title?: string }
  | { op: "sessions.messages"; sessionId: string; limit?: number }
  | { op: "approvals.list" }
  | { op: "budget.get"; sessionId: string };

/** 流句柄——chat_start / run_subscribe 返回，用于 stream_stop。 */
export type StreamHandle = {
  handleId: string;
  runId?: string;
  channelId: number;
};

export type ExportResult = {
  path: string;
  bytes: number;
};

export type UpdateInfo = {
  available: boolean;
  version?: string;
  notes?: string;
};

/** 命令签名映射——给 typed invoke 用（见 ipc/client.ts）。 */
export type IpcContract = {
  [IPC.connectionList]: { args: void; result: ConnectionProfile[] };
  [IPC.connectionSave]: { args: { input: ConnectionDraft }; result: ConnectionProfile };
  [IPC.connectionDelete]: { args: { id: string }; result: void };
  [IPC.connectionTest]: { args: { id?: string; draft?: ConnectionDraft }; result: HealthResult };
  [IPC.connectionActivate]: { args: { id: string }; result: ConnectionSession };
  [IPC.authLogin]: { args: { connectionId: string; password: string }; result: AuthSummary };
  [IPC.authLogout]: { args: { connectionId: string }; result: void };
  [IPC.apiRequest]: { args: { connectionId: string; operation: ApiOperation }; result: unknown };
  [IPC.chatStart]: {
    args: { connectionId: string; sessionId: string; content: string; clientRequestId: string };
    result: StreamHandle;
  };
  [IPC.runSubscribe]: { args: { connectionId: string; runId: string; afterSeq?: number }; result: StreamHandle };
  [IPC.streamStop]: { args: { handleId: string }; result: void };
  [IPC.artifactExport]: { args: { connectionId: string; artifactId: string }; result: ExportResult };
  [IPC.diagnosticsExport]: { args: void; result: ExportResult };
  [IPC.appCheckUpdate]: { args: void; result: UpdateInfo };
};
