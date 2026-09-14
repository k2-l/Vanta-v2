/**
 * 类型化 IPC 客户端——WebView 与 Rust Core 的唯一通道。
 *
 * - 生产（Tauri WebView）：走 `@tauri-apps/api` 的 invoke。
 * - 开发（普通浏览器 `npm run dev`，无 Tauri host）：走内置 mock，
 *   让 UI 可独立开发/验证，不依赖 Rust 编译产物。
 *
 * 无论哪条路径，错误都归一化为 ClientError（方案 §8.3）。
 */

import { toClientError } from "@/contracts/errors";
import type { IpcContract } from "@/contracts/ipc";
import { mockInvoke } from "./mock";

/** 是否运行在 Tauri WebView 内。 */
export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
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
    if (isTauri()) return await realInvoke(cmd, args);
    return await mockInvoke(cmd, args);
  } catch (err) {
    throw toClientError(err);
  }
}
