/**
 * 类型化 IPC 客户端——WebView 与 Rust Core 的唯一通道。
 *
 * 只允许在 Tauri WebView 中通过 `@tauri-apps/api` 调用真实 Rust Core。
 * 普通浏览器不提供后端回退，避免联调时误把内存假数据当成服务端状态。
 * 错误统一归一化为 ClientError（方案 §8.3）。
 */

import { toClientError } from "@/contracts/errors";
import type { IpcContract } from "@/contracts/ipc";

/** 是否运行在 Tauri WebView 内。 */
export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** 拒绝脱离 Tauri host 运行；桌面端不再提供浏览器 Mock。 */
export function requireTauri(): void {
  if (!isTauri()) throw new Error("Vanta GUI 必须在 Tauri 客户端中运行");
}

type Cmd = keyof IpcContract;

/** 惰性加载真实 invoke，避免浏览器环境解析 Tauri 内部模块报错。 */
async function realInvoke<C extends Cmd>(cmd: C, args: IpcContract[C]["args"]): Promise<IpcContract[C]["result"]> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke(cmd as string, (args ?? undefined) as Record<string, unknown> | undefined) as Promise<
    IpcContract[C]["result"]
  >;
}

export async function ipc<C extends Cmd>(cmd: C, args: IpcContract[C]["args"]): Promise<IpcContract[C]["result"]> {
  try {
    requireTauri();
    return await realInvoke(cmd, args);
  } catch (err) {
    throw toClientError(err);
  }
}
