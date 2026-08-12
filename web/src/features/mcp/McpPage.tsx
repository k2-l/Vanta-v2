import { useState, useEffect, useCallback } from "react";
import { api, type McpServer } from "@/shared/lib/api";
import { ModuleHeader, ModuleTitle } from "@/shared/components/ModuleHeader";

const MCP_STATUS: Record<string, { label: string; color: string; bg: string }> = {
  connected:    { label: "已连接", color: "#10B981", bg: "#10B98115" },
  disconnected: { label: "未连接", color: "#9BA3AF", bg: "#9BA3AF15" },
  connecting:   { label: "连接中", color: "#F59E0B", bg: "#F59E0B15" },
  error:        { label: "异常",   color: "#EF4444", bg: "#EF444415" },
};

const emptyForm = { name: "", command: "", args: "", env: "", enabled: true };

// 把表单拼成完整 command 字符串，供二次确认弹窗展示「将执行的 command 全文」
function buildCommandPreview(form: typeof emptyForm): string {
  const args = form.args.split(/[\n,]+/).map((a) => a.trim()).filter(Boolean);
  const parts = [form.command.trim(), ...args].filter(Boolean);
  return parts.join(" ") || "(空)";
}

function parseArgs(raw: string): string[] {
  return raw.split(/[\n,]+/).map((a) => a.trim()).filter(Boolean);
}

function parseEnv(raw: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of raw.split(/[\n,]+/)) {
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    const val = line.slice(eq + 1).trim();
    if (key) out[key] = val;
  }
  return out;
}

export function McpPage() {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [createConfirming, setCreateConfirming] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [deleteConfirming, setDeleteConfirming] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionName, setActionName] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ name: string; ok: boolean; error: string | null; tools: string[] } | null>(null);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setServers(await api.listMcpServers());
      setOffline(false);
    } catch {
      // harness 可能未启动；不覆盖已有列表，改用离线指示
      setOffline(true);
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  function openCreate() {
    setForm(emptyForm);
    setCreateConfirming(false);
    setShowCreate(true);
  }

  async function handleCreate() {
    if (!createConfirming) {
      if (!form.name.trim() || !form.command.trim()) return;
      setCreateConfirming(true); // 第一步：先展示将执行的 command 全文，再次点击才真正提交
      return;
    }
    setActionName(form.name);
    try {
      await api.createMcpServer({
        name: form.name.trim(),
        command: form.command.trim(),
        args: parseArgs(form.args),
        env: parseEnv(form.env),
        enabled: form.enabled,
        confirm: true,
      });
      await load();
      setShowCreate(false);
      setForm(emptyForm);
    } catch (e) { setError(`新建失败：${e}`); }
    setActionName(null);
  }

  async function handleDelete(name: string) {
    if (deleteConfirming === name) {
      setActionName(name);
      try {
        await api.deleteMcpServer(name, true);
        await load();
        setDeleteConfirming(null);
      } catch (e) { setError(`删除失败：${e}`); }
      setActionName(null);
    } else {
      setDeleteConfirming(name);
    }
  }

  async function handleTest(name: string) {
    setActionName(name);
    setTestResult(null);
    try {
      const res = await api.testMcpServer(name);
      setTestResult({ name, ...res });
    } catch (e) { setError(`测试失败：${e}`); }
    setActionName(null);
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "#F4F5F7" }}>
      {/* Offline / error banners */}
      {offline && (
        <div style={{ background: "#FFFBEB", borderBottom: "1px solid #FDE68A", padding: "7px 20px", fontSize: 11, color: "#92400E", flexShrink: 0 }}>
          ⚠ harness 服务未响应，MCP 管理功能暂不可用
        </div>
      )}
      {error && (
        <div style={{ background: "#FEF2F2", borderBottom: "1px solid #FECACA", padding: "8px 20px", display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          <span style={{ color: "#DC2626", fontSize: 12, flex: 1 }}>{error}</span>
          <button onClick={() => setError(null)} style={{ background: "none", border: "none", color: "#DC2626", cursor: "pointer", fontSize: 14, lineHeight: 1 }}>✕</button>
        </div>
      )}
      {/* Header */}
      <ModuleHeader
        title={<ModuleTitle>MCP Server</ModuleTitle>}
        actions={<>
          <span style={{ fontSize: 11, color: "#9BA3AF" }}>
            {servers.filter((s) => s.status === "connected").length} 已连接 · {servers.length} 总计
          </span>
          <button onClick={load} style={{ fontSize: 12, padding: "7px 14px", borderRadius: 8, background: "transparent", border: "1px solid #E2E5EA", color: "#6B7280", cursor: "pointer", fontFamily: "inherit" }}>
            刷新
          </button>
          <button onClick={openCreate} style={{ fontSize: 12, padding: "8px 18px", borderRadius: 8, background: "#4F6EF718", border: "1px solid #4F6EF744", color: "#4F6EF7", cursor: "pointer", fontFamily: "inherit" }}>
            ＋ 新建 Server
          </button>
        </>}
      />

      {/* Grid */}
      <div style={{ flex: 1, overflowY: "auto", padding: 24, display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(300px,1fr))", gap: 16, alignContent: "start" }}>
        {loading && servers.length === 0 && (
          <div style={{ gridColumn: "1/-1", textAlign: "center", padding: 40, fontSize: 13, color: "#9BA3AF" }}>加载中…</div>
        )}
        {!loading && servers.length === 0 && (
          <div style={{ gridColumn: "1/-1", textAlign: "center", padding: 60, fontSize: 13, color: "#9BA3AF" }}>
            暂无 MCP server<br />
            <button onClick={openCreate} style={{ marginTop: 12, fontSize: 12, padding: "7px 16px", borderRadius: 8, background: "#4F6EF718", border: "1px solid #4F6EF744", color: "#4F6EF7", cursor: "pointer", fontFamily: "inherit" }}>
              新建 Server
            </button>
          </div>
        )}
        {servers.map((s) => {
          const st = MCP_STATUS[s.status] ?? MCP_STATUS.disconnected;
          const connected = s.status === "connected";
          const isAction = actionName === s.name;
          const confirmingDelete = deleteConfirming === s.name;
          const isExpanded = expanded === s.name;
          const commandText = [s.command, ...s.args].filter(Boolean).join(" ");
          const result = testResult?.name === s.name ? testResult : null;
          return (
            <div key={s.name} style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 12, padding: "16px 18px", display: "flex", flexDirection: "column", gap: 12, borderTop: `3px solid ${connected ? "#10B981" : "#E2E5EA"}` }}>
              {/* Top row */}
              <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                <div style={{ width: 36, height: 36, borderRadius: 9, flexShrink: 0, background: connected ? "#10B98115" : "#F4F5F7", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>
                  {connected ? "◉" : "○"}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#1A1D23", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name}</div>
                  <div style={{ fontSize: 10, color: "#9BA3AF", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "monospace" }} title={commandText}>{commandText}</div>
                </div>
                <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 99, letterSpacing: 0.5, fontWeight: 600, color: st.color, background: st.bg, flexShrink: 0 }}>{st.label}</span>
              </div>

              {/* error 详情 */}
              {s.error && (
                <div style={{ fontSize: 10, color: "#DC2626", background: "#FEF2F2", border: "1px solid #FECACA", borderRadius: 6, padding: "6px 8px", wordBreak: "break-word" }}>
                  {s.error}
                </div>
              )}

              {/* env keys chips */}
              {s.env_keys.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {s.env_keys.map((k) => (
                    <span key={k} style={{ fontSize: 9, padding: "1px 7px", borderRadius: 99, background: "#4F6EF711", color: "#4F6EF7" }}>{k}</span>
                  ))}
                </div>
              )}

              {/* tool_count（可展开） */}
              <button
                onClick={() => setExpanded(isExpanded ? null : s.name)}
                disabled={s.tool_count === 0}
                style={{ display: "flex", alignItems: "center", gap: 6, background: "transparent", border: "none", padding: 0, cursor: s.tool_count > 0 ? "pointer" : "default", color: "#6B7280", fontFamily: "inherit", fontSize: 11, textAlign: "left" }}
              >
                <span>{s.tool_count > 0 ? (isExpanded ? "▾" : "▸") : "·"}</span>
                <span>{s.tool_count} 个工具</span>
              </button>
              {isExpanded && s.tool_count > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 3, paddingLeft: 16, maxHeight: 120, overflowY: "auto" }}>
                  {s.tools.length > 0
                    ? s.tools.map((t) => (
                        <span key={t.name} style={{ fontSize: 10, color: "#9BA3AF", fontFamily: "monospace" }}>{t.remote_name}</span>
                      ))
                    : <span style={{ fontSize: 10, color: "#C0C5CE" }}>详情见 GET /v1/mcp/servers/{s.name}</span>
                  }
                </div>
              )}

              {/* 测试结果 */}
              {result && (
                <div style={{ fontSize: 10, padding: "6px 8px", borderRadius: 6, background: result.ok ? "#10B98111" : "#FEF2F2", border: `1px solid ${result.ok ? "#10B98144" : "#FECACA"}`, color: result.ok ? "#10B981" : "#DC2626" }}>
                  {result.ok ? `✓ 连接成功，发现 ${result.tools.length} 个工具` : `✗ ${result.error ?? "连接失败"}`}
                </div>
              )}

              {/* Actions */}
              <div style={{ display: "flex", gap: 8, borderTop: "1px solid #F4F5F7", paddingTop: 10 }}>
                <button
                  onClick={() => handleTest(s.name)}
                  disabled={isAction}
                  style={{ flex: 1, fontSize: 11, padding: "6px 0", borderRadius: 7, cursor: isAction ? "default" : "pointer", fontFamily: "inherit", border: "1px solid #4F6EF744", background: "#4F6EF711", color: "#4F6EF7", opacity: isAction ? 0.5 : 1 }}
                >
                  {isAction ? "…" : "⟲ 测试连接"}
                </button>
                {confirmingDelete ? (
                  <div style={{ display: "flex", gap: 4 }}>
                    <button onClick={() => handleDelete(s.name)} disabled={isAction} style={{ fontSize: 11, padding: "6px 10px", borderRadius: 7, cursor: "pointer", fontFamily: "inherit", border: "1px solid #EF444433", background: "#EF444411", color: "#EF4444" }}>
                      确认删除
                    </button>
                    <button onClick={() => setDeleteConfirming(null)} style={{ fontSize: 11, padding: "6px 10px", borderRadius: 7, cursor: "pointer", fontFamily: "inherit", border: "1px solid #E2E5EA", background: "transparent", color: "#9BA3AF" }}>
                      取消
                    </button>
                  </div>
                ) : (
                  <button onClick={() => handleDelete(s.name)} style={{ fontSize: 11, padding: "6px 12px", borderRadius: 7, cursor: "pointer", fontFamily: "inherit", border: "1px solid #EF444433", background: "#EF444411", color: "#EF4444" }}>
                    删除
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* New Server Modal */}
      {showCreate && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.2)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
          <div style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 14, width: "100%", maxWidth: 520, boxShadow: "0 24px 64px rgba(0,0,0,0.1)" }}>
            <div style={{ display: "flex", alignItems: "center", padding: "16px 24px", borderBottom: "1px solid #E2E5EA" }}>
              <span style={{ flex: 1, fontSize: 14, fontWeight: 700, color: "#1A1D23" }}>新建 MCP Server</span>
              <button onClick={() => setShowCreate(false)} style={{ background: "transparent", border: "none", color: "#9BA3AF", cursor: "pointer", fontSize: 14, fontFamily: "inherit" }}>✕</button>
            </div>

            {!createConfirming ? (
              <>
                <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 14 }}>
                  <FieldBox label="名称（server name）">
                    <input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="e.g. filesystem"
                      style={fieldStyle} />
                  </FieldBox>
                  <FieldBox label="命令（command）">
                    <input value={form.command} onChange={(e) => setForm((f) => ({ ...f, command: e.target.value }))} placeholder="e.g. npx"
                      style={fieldStyle} />
                  </FieldBox>
                  <FieldBox label="参数（args，每行一个或逗号分隔）">
                    <textarea value={form.args} onChange={(e) => setForm((f) => ({ ...f, args: e.target.value }))} placeholder={"e.g. -y\n@modelcontextprotocol/server-filesystem\n/tmp"} rows={3}
                      style={{ ...fieldStyle, resize: "vertical", fontFamily: "monospace" }} />
                  </FieldBox>
                  <FieldBox label="环境变量（env，每行 KEY=VALUE）">
                    <textarea value={form.env} onChange={(e) => setForm((f) => ({ ...f, env: e.target.value }))} placeholder={"e.g. API_KEY=xxx"} rows={2}
                      style={{ ...fieldStyle, resize: "vertical", fontFamily: "monospace" }} />
                  </FieldBox>
                  <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "#6B7280", cursor: "pointer" }}>
                    <input type="checkbox" checked={form.enabled} onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))} />
                    启用（创建后立即热挂载）
                  </label>
                </div>
                <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, padding: "14px 24px", borderTop: "1px solid #E2E5EA" }}>
                  <button onClick={() => setShowCreate(false)} style={{ fontSize: 12, padding: "7px 16px", borderRadius: 8, background: "transparent", border: "1px solid #E2E5EA", color: "#6B7280", cursor: "pointer", fontFamily: "inherit" }}>取消</button>
                  <button onClick={handleCreate} style={{ fontSize: 12, padding: "8px 18px", borderRadius: 8, background: "#4F6EF718", border: "1px solid #4F6EF744", color: "#4F6EF7", cursor: "pointer", fontFamily: "inherit", opacity: form.name.trim() && form.command.trim() ? 1 : 0.4 }}>
                    下一步：确认
                  </button>
                </div>
              </>
            ) : (
              <>
                {/* 二次确认：展示将执行的 command 全文 */}
                <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 12 }}>
                  <div style={{ fontSize: 11, color: "#92400E", background: "#FFFBEB", border: "1px solid #FDE68A", borderRadius: 8, padding: "10px 12px" }}>
                    ⚠ 即将启动以下子进程并注册其工具到全局工具集，请确认无误：
                  </div>
                  <div style={{ fontSize: 12, fontFamily: "monospace", background: "#1A1D23", color: "#E2E5EA", borderRadius: 8, padding: "12px 14px", wordBreak: "break-all", lineHeight: 1.6 }}>
                    $ {buildCommandPreview(form)}
                  </div>
                  {Object.keys(parseEnv(form.env)).length > 0 && (
                    <div style={{ fontSize: 11, color: "#6B7280" }}>
                      环境变量：{Object.keys(parseEnv(form.env)).join(", ")}
                    </div>
                  )}
                </div>
                <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, padding: "14px 24px", borderTop: "1px solid #E2E5EA" }}>
                  <button onClick={() => setCreateConfirming(false)} style={{ fontSize: 12, padding: "7px 16px", borderRadius: 8, background: "transparent", border: "1px solid #E2E5EA", color: "#6B7280", cursor: "pointer", fontFamily: "inherit" }}>返回修改</button>
                  <button onClick={handleCreate} disabled={!!actionName} style={{ fontSize: 12, padding: "8px 18px", borderRadius: 8, background: "#EF444418", border: "1px solid #EF444444", color: "#EF4444", cursor: actionName ? "wait" : "pointer", fontFamily: "inherit" }}>
                    {actionName ? "创建中…" : "确认创建"}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

const fieldStyle: React.CSSProperties = {
  background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "8px 12px",
  color: "#1A1D23", fontSize: 12, fontFamily: "inherit", outline: "none", width: "100%", boxSizing: "border-box",
};

function FieldBox({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{ fontSize: 10, color: "#C0C5CE", letterSpacing: 1 }}>{label}</span>
      {children}
    </div>
  );
}
