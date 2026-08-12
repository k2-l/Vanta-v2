import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

const components: Components = {
  h1: ({ children }) => (
    <h2 style={{ margin: "0 0 10px", fontSize: 16, color: "#1A1D23", fontWeight: 800 }}>{children}</h2>
  ),
  h2: ({ children }) => (
    <h3 style={{ margin: "18px 0 8px", fontSize: 14, color: "#374151", fontWeight: 700 }}>{children}</h3>
  ),
  h3: ({ children }) => (
    <h4 style={{ margin: "14px 0 6px", fontSize: 12, color: "#6B7280", letterSpacing: 1, textTransform: "uppercase", fontWeight: 700 }}>{children}</h4>
  ),
  h4: ({ children }) => (
    <h4 style={{ margin: "12px 0 6px", fontSize: 11, color: "#9BA3AF", letterSpacing: 1, textTransform: "uppercase", fontWeight: 700 }}>{children}</h4>
  ),
  p: ({ children }) => (
    <p style={{ margin: "6px 0", fontSize: 12, color: "#374151", lineHeight: 1.85 }}>{children}</p>
  ),
  code: ({ children, className }) => {
    // Block code (inside pre) — no inline background
    if (className) {
      return (
        <code style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>{children}</code>
      );
    }
    // Inline code
    return (
      <code style={{ background: "#E2E5EA", color: "#4F6EF7", padding: "1px 6px", borderRadius: 4, fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}>{children}</code>
    );
  },
  pre: ({ children }) => (
    <pre style={{ background: "#1A1D23", color: "#E2E5EA", padding: "14px 18px", borderRadius: 8, overflowX: "auto", fontSize: 11, lineHeight: 1.7, margin: "8px 0" }}>{children}</pre>
  ),
  ul: ({ children }) => (
    <ul style={{ paddingLeft: 18, margin: "6px 0", listStyleType: "disc" }}>{children}</ul>
  ),
  ol: ({ children }) => (
    <ol style={{ paddingLeft: 18, margin: "6px 0" }}>{children}</ol>
  ),
  li: ({ children }) => (
    <li style={{ fontSize: 12, color: "#6B7280", margin: "3px 0" }}>{children}</li>
  ),
  table: ({ children }) => (
    <div style={{ overflowX: "auto", margin: "8px 0" }}>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th style={{ border: "1px solid #E2E5EA", padding: "6px 10px", textAlign: "left", background: "#F4F5F7", fontWeight: 700 }}>{children}</th>
  ),
  td: ({ children }) => (
    <td style={{ border: "1px solid #E2E5EA", padding: "6px 10px", textAlign: "left" }}>{children}</td>
  ),
  blockquote: ({ children }) => (
    <blockquote style={{ borderLeft: "3px solid #4F6EF7", margin: "8px 0", padding: "4px 12px", color: "#6B7280", fontStyle: "italic" }}>{children}</blockquote>
  ),
  a: ({ href, children }) => (
    <a href={href} style={{ color: "#4F6EF7", textDecoration: "underline" }} target="_blank" rel="noreferrer">{children}</a>
  ),
  hr: () => (
    <hr style={{ border: "none", borderTop: "1px solid #E2E5EA", margin: "12px 0" }} />
  ),
  strong: ({ children }) => (
    <strong style={{ color: "#1A1D23" }}>{children}</strong>
  ),
  input: ({ type, checked, disabled }) => {
    if (type === "checkbox") {
      return <input type="checkbox" checked={checked} disabled={disabled} style={{ marginRight: 6 }} readOnly />;
    }
    return <input type={type} />;
  },
};

export function MarkdownPreview({ content, style }: { content: string; style?: React.CSSProperties }) {
  return (
    <div style={style}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
