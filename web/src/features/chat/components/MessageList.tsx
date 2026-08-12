import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Wrench, ChevronDown, ChevronRight, AlertTriangle, ClipboardCheck } from "lucide-react";
import { useChat, type StreamItem } from "@/store/chat";
import { useSend } from "../useSend";
import { ApprovalPrompt } from "./ApprovalPrompt";

// 主代理身份色（转录式：助手满宽 + ⬡ 标；子代理用紫）
const MAIN = "#4F6EF7";
const SUB = "#7C3AED";

// 剥离 agent 的 <subgoal>…</subgoal> 内部标记：它是后端任务进度跟踪用的约定，不该展示给用户。
// 同时处理流式中尚未闭合的尾部标签，避免"闪现半个标签"。
function stripSubgoals(s: string): string {
  return s
    .replace(/<subgoal>[\s\S]*?<\/subgoal>\s*/g, "")
    .replace(/<subgoal>[\s\S]*$/, "");
}

export function MessageList() {
  const messages = useChat((s) => s.messages);
  const turn = useChat((s) => s.turn);
  const pendingApprovals = useChat((s) => s.pendingApprovals);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [waitingSec, setWaitingSec] = useState(0);
  const sendMsg = useSend();

  function retry() {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (!lastUser || turn.inFlight) return;
    sendMsg(lastUser.content);
  }

  // 超过 3 秒无事件时显示"排队中"提示，reset 当流式内容开始
  useEffect(() => {
    if (!turn.inFlight) { setWaitingSec(0); return; }
    if (turn.streamItems.length > 0) { setWaitingSec(0); return; }
    setWaitingSec(0);
    const t = setInterval(() => setWaitingSec((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [turn.inFlight, turn.streamItems.length]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, turn.streamItems.length, pendingApprovals.length]);

  return (
    <div style={{
      flex: 1,
      minHeight: 0,
      overflowY: "auto",
      padding: "24px 28px",
      display: "flex",
      flexDirection: "column",
      gap: 18,
    }}>
      {messages.length === 0 && !turn.inFlight && (
        <div style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 12,
          color: "#C0C5CE",
          paddingTop: 80,
        }}>
          <span style={{ fontSize: 32 }}>⬡</span>
          <span style={{ fontSize: 13 }}>向 Master Agent 发送第一条指令</span>
        </div>
      )}

      {messages.map((m) => (
        <Turn key={m.id} role={m.role} content={m.content} createdAt={m.created_at} items={m.items} />
      ))}

      {!turn.inFlight && turn.workerFailed && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0", paddingLeft: 27 }}>
          <span style={{ fontSize: 11, color: "#EF4444" }}>⚠ 上一轮执行失败</span>
          <button
            onClick={retry}
            style={{
              fontSize: 11, padding: "4px 12px", borderRadius: 6,
              background: "#EF444411", border: "1px solid #EF444444",
              color: "#EF4444", cursor: "pointer", fontFamily: "inherit",
            }}
          >
            ↺ 重试
          </button>
        </div>
      )}

      {turn.inFlight && (
        <div style={{ display: "flex", gap: 9 }}>
          <span style={{ fontSize: 18, color: MAIN, flexShrink: 0, lineHeight: 1.4, marginTop: 1 }}>⬡</span>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, fontSize: 11, fontWeight: 500, color: MAIN }}>
              主代理
              <span style={{ display: "inline-flex", gap: 2, verticalAlign: "middle" }}>
                <span style={{ display: "inline-block", width: 4, height: 4, borderRadius: "50%", background: "currentColor", animation: "bounce 1s infinite 0ms" }} />
                <span style={{ display: "inline-block", width: 4, height: 4, borderRadius: "50%", background: "currentColor", animation: "bounce 1s infinite 150ms" }} />
                <span style={{ display: "inline-block", width: 4, height: 4, borderRadius: "50%", background: "currentColor", animation: "bounce 1s infinite 300ms" }} />
              </span>
            </div>
            {turn.streamItems.length === 0 ? (
              waitingSec >= 3 ? (
                <div style={{ fontSize: 12, color: "#F59E0B", display: "flex", alignItems: "center", gap: 6 }}>
                  <span>⏳</span>
                  <span>响应较慢，请稍候（{waitingSec}s）</span>
                </div>
              ) : (
                <div style={{ fontSize: 12, color: "#9BA3AF", fontStyle: "italic" }}>思考中…</div>
              )
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {turn.streamItems.map((item, i) => (
                  <StreamItemView key={i} item={item} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      <ApprovalPrompt />

      <div ref={bottomRef} />
    </div>
  );
}

function StreamItemView({ item }: { item: StreamItem }) {
  switch (item.kind) {
    case "worker_step":
      return <WorkerStepBadge {...item} />;
    case "tool_call":
      return <ToolCallCard {...item} />;
    case "tool_error":
      return <ToolErrorCard {...item} />;
    case "text": {
      const txt = stripSubgoals(item.content);
      if (!txt.trim()) return null;
      return (
        <div style={{ fontSize: 13, color: "#374151", lineHeight: 1.65 }}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{txt}</ReactMarkdown>
        </div>
      );
    }
  }
}

// 子代理派发：细「步骤条」（紫），替代旧的橙徽章
function WorkerStepBadge({ stepNo, worker, instruction }: { stepNo: number; worker: string; instruction: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "2px 0", fontSize: 12 }}>
      <span style={{
        fontFamily: "monospace",
        fontSize: 10,
        fontWeight: 700,
        color: SUB,
        background: "#7C3AED14",
        padding: "1px 7px",
        borderRadius: 20,
        flexShrink: 0,
      }}>
        步骤 {stepNo}
      </span>
      <span style={{ color: "#C0C5CE", flexShrink: 0 }}>→</span>
      <span style={{ fontWeight: 600, color: SUB, flexShrink: 0 }}>{worker}</span>
      <span style={{ color: "#9BA3AF", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {instruction.slice(0, 60)}
      </span>
    </div>
  );
}

function ToolCallCard({ tool, inputs, result }: {
  tool: string;
  inputs: Record<string, unknown>;
  result?: { ok: boolean; output: string };
}) {
  const [expanded, setExpanded] = useState(false);
  const hasResult = !!result;
  // board.write 成功 → 挂「已上看板」chip，把对话与右栏看板串起来
  const boardWrite = tool === "board" && inputs?.action === "write" && !!result?.ok;
  const boardKind = typeof inputs?.kind === "string" ? inputs.kind : "";

  const shortArgs = Object.entries(inputs)
    .map(([k, v]) => `${k}=${JSON.stringify(v).replace(/^"|"$/g, "").slice(0, 50)}`)
    .join("  ")
    .slice(0, 120);

  return (
    <>
      <div style={{
        overflow: "hidden",
        borderRadius: 10,
        border: "1px solid #E2E5EA",
        background: "#FFFFFF",
        fontSize: 12,
      }}>
        <button
          style={{
            display: "flex",
            width: "100%",
            alignItems: "center",
            gap: 8,
            padding: "7px 11px",
            textAlign: "left",
            background: "transparent",
            border: "none",
            cursor: hasResult ? "pointer" : "default",
            fontFamily: "inherit",
          }}
          onClick={() => hasResult && setExpanded((e) => !e)}
          disabled={!hasResult}
        >
          <Wrench style={{ width: 12, height: 12, flexShrink: 0, color: "#9BA3AF" }} />
          <span style={{ fontFamily: "monospace", fontWeight: 600, color: "#1A1D23" }}>{tool}</span>
          {shortArgs && (
            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "monospace", color: "#9BA3AF" }}>
              {shortArgs}
            </span>
          )}
          <span style={{ marginLeft: "auto", flexShrink: 0, paddingLeft: 8 }}>
            {hasResult ? (
              <span style={{ color: result!.ok ? "#10B981" : "#EF4444" }}>
                {result!.ok ? "✓ 完成" : "✗ 失败"}
              </span>
            ) : (
              <span style={{ color: "#F59E0B" }}>运行中…</span>
            )}
          </span>
          {hasResult && (
            <span style={{ color: "#C0C5CE" }}>
              {expanded ? <ChevronDown style={{ width: 12, height: 12 }} /> : <ChevronRight style={{ width: 12, height: 12 }} />}
            </span>
          )}
        </button>
        {expanded && result && (
          <pre style={{
            maxHeight: 208,
            overflow: "auto",
            borderTop: "1px solid #E2E5EA",
            padding: "8px 11px",
            fontSize: 11,
            lineHeight: 1.6,
            color: "#9BA3AF",
            whiteSpace: "pre-wrap",
            wordBreak: "break-all" as const,
            margin: 0,
          }}>
            {result.output.slice(0, 3000)}
          </pre>
        )}
      </div>
      {boardWrite && (
        <div style={{ marginTop: 3 }}>
          <span style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
            fontSize: 11,
            padding: "2px 9px",
            borderRadius: 20,
            background: "#4F6EF714",
            color: MAIN,
          }}>
            <ClipboardCheck style={{ width: 12, height: 12 }} />
            已上看板{boardKind ? ` · ${boardKind}` : ""}
          </span>
        </div>
      )}
    </>
  );
}

function ToolErrorCard({ tool, error_code, message, retryable }: {
  tool: string;
  error_code: string;
  message: string;
  retryable: boolean;
}) {
  return (
    <div style={{
      overflow: "hidden",
      borderRadius: 10,
      border: "1px solid #FCA5A533",
      background: "#FFF1F2",
      fontSize: 12,
    }}>
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "7px 11px",
      }}>
        <AlertTriangle style={{ width: 12, height: 12, flexShrink: 0, color: "#EF4444" }} />
        <span style={{ fontFamily: "monospace", fontWeight: 600, color: "#EF4444" }}>{tool}</span>
        <span style={{
          display: "inline-flex",
          alignItems: "center",
          borderRadius: 4,
          background: "#FEE2E2",
          border: "1px solid #FCA5A5",
          padding: "1px 6px",
          fontFamily: "monospace",
          fontSize: 10,
          fontWeight: 700,
          color: "#DC2626",
          flexShrink: 0,
        }}>
          {error_code}
        </span>
        <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#9BA3AF" }}>
          {message}
        </span>
        <span style={{ marginLeft: "auto", flexShrink: 0, paddingLeft: 8, color: retryable ? "#F59E0B" : "#EF4444", fontSize: 11 }}>
          {retryable ? "系统正在重试" : "执行终止"}
        </span>
      </div>
    </div>
  );
}


function fmtTime(iso: string | undefined): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
}

// 转录式一轮：user=右侧紧凑块；assistant=满宽（⬡ + 主代理 + 分步 items 或 markdown 正文），无气泡容器
function Turn({ role, content, createdAt, items }: { role: string; content: string; createdAt?: string; items?: StreamItem[] }) {
  const isUser = role === "user";
  const timeStr = fmtTime(createdAt);
  const [hovered, setHovered] = useState(false);
  const [copied, setCopied] = useState(false);

  function copyContent() {
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  }

  const copyBtn = hovered && (
    <button onClick={copyContent} title="复制内容" style={{
      background: "none", border: "none", cursor: "pointer",
      fontSize: 10, color: copied ? "#10B981" : "#C0C5CE",
      padding: 0, fontFamily: "inherit", transition: "color 0.2s",
    }}>
      {copied ? "✓ 已复制" : "⧉ 复制"}
    </button>
  );

  if (isUser) {
    return (
      <div
        style={{ display: "flex", justifyContent: "flex-end" }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        <div style={{ maxWidth: "74%", minWidth: 0 }}>
          <div style={{
            padding: "9px 13px",
            borderRadius: 12,
            borderTopRightRadius: 4,
            background: "#EEF0FF",
            border: "1px solid #D9DEFF",
            fontSize: 13,
            color: "#374151",
            lineHeight: 1.6,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}>
            {content}
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 8, marginTop: 3, height: 14 }}>
            {copyBtn}
            {timeStr && <span style={{ fontSize: 9, color: "#C0C5CE", letterSpacing: 0.5 }}>{timeStr}</span>}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      style={{ display: "flex", gap: 9 }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <span style={{ fontSize: 18, color: MAIN, flexShrink: 0, lineHeight: 1.4, marginTop: 1 }}>⬡</span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3, height: 15 }}>
          <span style={{ fontSize: 11, fontWeight: 500, color: MAIN }}>主代理</span>
          {timeStr && <span style={{ fontSize: 9, color: "#C0C5CE", letterSpacing: 0.5 }}>{timeStr}</span>}
          {copyBtn}
        </div>
        {items && items.length > 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {items.map((item, i) => <StreamItemView key={i} item={item} />)}
          </div>
        ) : (
          <div style={{ fontSize: 13, color: "#374151", lineHeight: 1.65 }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{stripSubgoals(content)}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}
