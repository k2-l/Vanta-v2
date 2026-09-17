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

/** 主动上下文压缩预览；提交前允许用户编辑 summary。 */
export type CompressPreview = {
  summary: string;
  upto: string;
  messages: number;
  tokens_before: number;
  tokens_after: number;
};

/** 兼容本地压缩控件的旧类型名。 */
export type CompactionPreview = CompressPreview;

/** 后端 SSE 经 Rust Core 解析后，通过有序 Tauri Channel 送达的帧。 */
export type { StreamPacket as ChatStreamPacket } from "./stream";
