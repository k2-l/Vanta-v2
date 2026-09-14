/**
 * 归一化客户端错误模型（方案 §8.3）。
 *
 * 所有 Rust command 失败都归一化为 ClientError，前端按 `kind` 决定呈现，
 * 不解析后端自然语言字符串。
 */

export type ClientErrorKind =
  | "offline"
  | "timeout"
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "conflict"
  | "validation"
  | "protocol"
  | "backend"
  | "desktop";

export type ClientError = {
  kind: ClientErrorKind;
  /** 后端/协议错误码（若有），用于精细分支，仍不面向用户展示。 */
  code?: string;
  /** 诊断用消息，可展示但不作为逻辑判断依据。 */
  message: string;
  retryable: boolean;
  requestId?: string;
  details?: unknown;
};

export function isClientError(v: unknown): v is ClientError {
  return (
    typeof v === "object" &&
    v !== null &&
    typeof (v as ClientError).kind === "string" &&
    typeof (v as ClientError).message === "string" &&
    typeof (v as ClientError).retryable === "boolean"
  );
}

/** 把任意 invoke 抛出的错误规整为 ClientError（Rust 侧已归一化，此处兜底非受控异常）。 */
export function toClientError(err: unknown): ClientError {
  if (isClientError(err)) return err;
  if (err instanceof Error) {
    return { kind: "desktop", message: err.message, retryable: false };
  }
  if (typeof err === "string") {
    return { kind: "desktop", message: err, retryable: false };
  }
  return { kind: "desktop", message: "未知桌面错误", retryable: false, details: err };
}

const KIND_LABELS: Record<ClientErrorKind, string> = {
  offline: "无法连接后端",
  timeout: "请求超时",
  unauthorized: "登录已失效",
  forbidden: "无权限执行",
  not_found: "资源不存在",
  conflict: "状态冲突",
  validation: "输入校验失败",
  protocol: "协议不兼容",
  backend: "后端返回错误",
  desktop: "桌面客户端错误",
};

export function clientErrorLabel(err: ClientError): string {
  return KIND_LABELS[err.kind] ?? "错误";
}
