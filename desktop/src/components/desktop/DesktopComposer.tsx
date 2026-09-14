/**
 * 桌面输入器（规范 §4.1）——多行输入、发送 / 停止状态机。
 * 停止按钮只在运行期间出现；Enter 发送、Shift+Enter 换行。
 */

import { useEffect, useRef } from "react";
import { Send, Square } from "lucide-react";
import { Button } from "@/components/Button";

export function DesktopComposer({
  value,
  onChange,
  onSend,
  onStop,
  streaming = false,
  disabled = false,
  placeholder = "输入消息…",
  hint = "Enter 发送 · Shift + Enter 换行",
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop?: () => void;
  streaming?: boolean;
  disabled?: boolean;
  placeholder?: string;
  hint?: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 176)}px`;
  }, [value]);

  return (
    <div className="mx-auto w-full max-w-3xl">
      <div
        className="flex items-end gap-2 rounded-[var(--radius-lg)] border p-2 transition-colors focus-within:border-[var(--accent-line)]"
        style={{ borderColor: "var(--border)", background: "var(--surface-overlay)" }}
      >
        <textarea
          ref={ref}
          value={value}
          rows={1}
          placeholder={placeholder}
          disabled={disabled && !streaming}
          className="select-text max-h-44 min-h-9 flex-1 resize-none bg-transparent px-2 py-2 text-[13px] leading-relaxed outline-none"
          style={{ color: "var(--fg)" }}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              if (!streaming) onSend();
            }
          }}
        />
        {streaming ? (
          <Button size="sm" variant="secondary" onClick={onStop}>
            <Square size={13} />
            停止
          </Button>
        ) : (
          <Button size="sm" disabled={disabled || !value.trim()} onClick={onSend}>
            <Send size={14} />
            发送
          </Button>
        )}
      </div>
      <p className="mt-2 text-center text-[11px]" style={{ color: "var(--fg-subtle)" }}>
        {hint}
      </p>
    </div>
  );
}
