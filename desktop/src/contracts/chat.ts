export type SessionSummary = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system" | (string & {});
  content: string;
  created_at: string;
};

/** 后端 SSE 经 Rust Core 解析后，通过有序 Tauri Channel 送达的帧。 */
export type { StreamPacket as ChatStreamPacket } from "./stream";
