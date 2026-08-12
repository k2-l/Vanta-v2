import type React from "react";
import { useRef } from "react";

const DEFAULT_STYLE: React.CSSProperties = {
  width: "100%",
  height: "100%",
  background: "#F4F5F7",
  border: "none",
  outline: "none",
  resize: "none",
  padding: "20px 28px",
  boxSizing: "border-box",
  color: "#374151",
  fontSize: 12,
  lineHeight: 1.85,
  fontFamily: "'JetBrains Mono', monospace",
};

export function MarkdownEditor({
  value,
  onChange,
  style,
}: {
  value: string;
  onChange: (v: string) => void;
  style?: React.CSSProperties;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Tab") return;
    e.preventDefault();

    const el = ref.current;
    if (!el) return;

    const start = el.selectionStart;
    const end = el.selectionEnd;

    if (e.shiftKey) {
      // Shift+Tab: remove up to 2 leading spaces before cursor
      const before = value.slice(0, start);
      const spacesToRemove = Math.min(2, before.length - before.replace(/ {1,2}$/, "").length);
      if (spacesToRemove === 0) return;
      const newValue = value.slice(0, start - spacesToRemove) + value.slice(end);
      onChange(newValue);
      // Restore cursor position after React re-render
      requestAnimationFrame(() => {
        el.selectionStart = start - spacesToRemove;
        el.selectionEnd = end - spacesToRemove;
      });
    } else {
      // Tab: insert 2 spaces
      const newValue = value.slice(0, start) + "  " + value.slice(end);
      onChange(newValue);
      requestAnimationFrame(() => {
        el.selectionStart = start + 2;
        el.selectionEnd = start + 2;
      });
    }
  }

  return (
    <textarea
      ref={ref}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={handleKeyDown}
      style={{ ...DEFAULT_STYLE, ...style }}
    />
  );
}
