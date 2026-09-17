import type { ChatStreamPacket } from "@/contracts/chat";
import type { StreamHandle } from "@/contracts/ipc";
import { toClientError } from "@/contracts/errors";
import { requireTauri } from "./client";

export type StartChatArgs = {
  connectionId: string;
  sessionId?: string;
  content: string;
  clientRequestId: string;
};

/** Channel 不是普通 JSON 参数，因此流式命令在类型化 invoke 之上单独封装。 */
export async function startChat(
  args: StartChatArgs,
  onEvent: (packet: ChatStreamPacket) => void,
): Promise<StreamHandle> {
  try {
    requireTauri();
    const { Channel, invoke } = await import("@tauri-apps/api/core");
    const channel = new Channel<ChatStreamPacket>();
    channel.onmessage = onEvent;
    return await invoke<StreamHandle>("chat_start", { ...args, onEvent: channel });
  } catch (error) {
    throw toClientError(error);
  }
}
