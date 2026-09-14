/**
 * 多服务器连接模型（方案 §9）。
 *
 * 凭据（JWT/刷新令牌/API Key/密码）永不进入前端，只保存在 Rust CredentialVault。
 * 前端只见到 ConnectionProfile（非敏感）与 AuthSummary（authenticated + 到期）。
 */

export type TlsPolicy = "system" | "custom_ca";

export type ConnectionProfile = {
  id: string;
  label: string;
  baseUrl: string;
  tlsPolicy: TlsPolicy;
  lastConnectedAt?: string;
  lastKnownVersion?: string;
};

/** connection_save 入参（草稿）。 */
export type ConnectionDraft = {
  id?: string;
  label: string;
  baseUrl: string;
  tlsPolicy?: TlsPolicy;
};

/** 连接状态机（方案 §9.2）——全局，侧栏/标题栏/页面统一呈现。 */
export type ConnectionStatus =
  | "unconfigured"
  | "testing"
  | "unauthenticated"
  | "authenticating"
  | "online"
  | "degraded"
  | "offline"
  | "reconnecting";

/** connection_test 结果。 */
export type HealthResult = {
  ok: boolean;
  /** 后端 server 版本（/health.version）。 */
  serverVersion?: string;
  workerModel?: string;
  /** 能力协商结果；后端未提供时为 undefined，GUI 据此隐藏未实现功能。 */
  capabilities?: ServerCapabilities;
  latencyMs?: number;
};

/** 能力协商（方案 §13.2）；后端补齐前多为 false / 缺省。 */
export type ServerCapabilities = {
  apiVersion?: string;
  runSnapshot: boolean;
  eventReplay: boolean;
  runCancel: boolean;
  artifactExport: boolean;
};

/** connection_activate 结果——一次活动连接会话。 */
export type ConnectionSession = {
  connectionId: string;
  status: ConnectionStatus;
  auth: AuthSummary;
  health: HealthResult;
};

/** 认证摘要——前端只见布尔与到期，永不见 token。 */
export type AuthSummary = {
  authenticated: boolean;
  expiresAt?: string;
  userLabel?: string;
};

export const DEFAULT_CAPABILITIES: ServerCapabilities = {
  runSnapshot: false,
  eventReplay: false,
  runCancel: false,
  artifactExport: false,
};
