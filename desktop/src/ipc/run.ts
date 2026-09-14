import type { StreamPacket } from "@/contracts/stream";
import type { StreamHandle } from "@/contracts/ipc";
import { toClientError } from "@/contracts/errors";
import { isTauri } from "./client";
import { mockRunSubscribe } from "./mock";

export type RunSubscribeArgs = {
  connectionId: string;
  runId: string;
  afterSeq?: number;
};

/**
 * 订阅运行（Plan G2）——Rust Core 拉取 phases 快照并轮询推送，前端按 phase id 去重、
 * 断线后重新订阅（重拉快照而非按 seq 重放）。Channel 非普通 JSON 参数，单独封装。
 */
export async function runSubscribe(
  args: RunSubscribeArgs,
  onEvent: (packet: StreamPacket) => void,
): Promise<StreamHandle> {
  try {
    if (!isTauri()) return await mockRunSubscribe(args, onEvent);
    const { Channel, invoke } = await import("@tauri-apps/api/core");
    const channel = new Channel<StreamPacket>();
    channel.onmessage = onEvent;
    return await invoke<StreamHandle>("run_subscribe", { ...args, onEvent: channel });
  } catch (error) {
    throw toClientError(error);
  }
}
