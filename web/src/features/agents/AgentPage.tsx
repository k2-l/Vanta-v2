import { useState, useEffect, useCallback } from "react";
import { api, type SuiteAgent } from "@/shared/lib/api";
import { MarkdownPreview } from "@/shared/components/MarkdownPreview";
import { MarkdownEditor } from "@/shared/components/MarkdownEditor";


const STATUS_META: Record<string, { label: string; color: string; bg: string }> = {
  true:     { label: "在线",   color: "#10B981", bg: "#10B98118" },
  false:    { label: "已停用", color: "#6B7280", bg: "#6B728018" },
};

const COLORS = ["#4F6EF7","#FF6B35","#7C3AED","#10B981","#F59E0B","#EC4899"];

// Derive a stable color from the agent id so it survives page refresh
function agentColor(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return COLORS[h % COLORS.length];
}

// UI-only display fields (not persisted)
type AgentLocal = SuiteAgent & {
  color: string;
  avatar: string;
};

function toLocal(a: SuiteAgent): AgentLocal {
  return {
    ...a,                                    // includes max_tokens, temperature, allow_autonomous, enable_critic from API
    color:         agentColor(a.id),         // deterministic — stable across refreshes
    avatar:        a.name ? a.name[0].toUpperCase() : "A",
  };
}


export function AgentPage() {
  const [agents, setAgents] = useState<AgentLocal[]>([]);
  const [draft, setDraft] = useState<AgentLocal | null>(null);
  const [bodyTab, setBodyTab] = useState<"edit" | "preview">("preview");
  const [showNew, setShowNew] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [delConfirm, setDelConfirm] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [workerModel, setWorkerModel] = useState("");
  const [newForm, setNewForm] = useState({ name: "", desc: "" });
  const [dirty, setDirty] = useState(false);
  const [availableTools, setAvailableTools] = useState<{ name: string; category: string }[]>([]);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const raw = await api.listAgents();
      const locals = raw.map(toLocal);
      setAgents(locals);
      setDraft((prev) => prev ?? (locals.length > 0 ? { ...locals[0] } : null));
    } catch (e) {
      setError(`加载失败：${e}`);
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    api.health().then((h) => setWorkerModel(h.worker_model)).catch(() => {});
  }, []);
  useEffect(() => {
    api.listTools()
      .then((list) => setAvailableTools(list))
      .catch(() => {});
  }, []);

  const upd = (patch: Partial<AgentLocal>) => { setDraft((d) => d ? { ...d, ...patch } : d); setDirty(true); };

  async function save() {
    if (!draft) return;
    try {
      await api.updateAgent(draft.id, {
        name:             draft.name,
        description:      draft.description,
        content:          draft.content,
        tools:            draft.tools,
        model:            draft.model ?? undefined,
        active:           draft.active,
        max_tokens:       draft.max_tokens,
        temperature:      draft.temperature,
        allow_autonomous: draft.allow_autonomous,
        enable_critic:    draft.enable_critic,
      });
      setAgents((p) => p.map((a) => a.id === draft.id ? draft : a));
      setDirty(false);
      showToast("已保存");
    } catch (e) { setError(`保存失败：${e}`); }
  }

  async function toggleActive() {
    if (!draft) return;
    const newActive = !draft.active;
    upd({ active: newActive });
    try {
      await api.updateAgent(draft.id, { active: newActive });
      setAgents((p) => p.map((a) => a.id === draft.id ? { ...a, active: newActive } : a));
      showToast(newActive ? "已启动" : "已暂停");
    } catch (e) {
      upd({ active: !newActive }); // 回滚
      setError(`操作失败：${e}`);
    }
  }

  async function createAgent() {
    if (!newForm.name.trim()) return;
    const md = `---\nname: ${newForm.name.trim()}\ndescription: ${newForm.desc}\nstatus: idle\n---\n\n## 核心职责\n\n${newForm.desc || "在此描述 Agent 的工作流程。"}`;
    try {
      const ag = await api.registerAgent(md);
      await load();
      const local = toLocal(ag);
      setDraft({ ...local });
      setShowNew(false);
      setNewForm({ name: "", desc: "" });
    } catch (e) { setError(`创建失败：${e}`); }
  }

  async function scanAgents() {
    setScanning(true);
    try {
      const { registered, skipped } = await api.scanAgents();
      const raw = await api.listAgents();
      const locals = raw.map(toLocal);
      setAgents(locals);
      setDraft((prev) => {
        if (!prev) return locals[0] ? { ...locals[0] } : null;
        const refreshed = locals.find((a) => a.id === prev.id);
        return refreshed ? { ...refreshed } : prev;
      });
      setDirty(false);
      showToast(registered > 0
        ? `已注册 ${registered} 个 Agent${skipped > 0 ? `，${skipped} 个跳过` : ""}`
        : "workspace/agents/ 中没有新的 Agent 需要注册");
    } catch (e) { setError(`扫描失败：${e}`); }
    setScanning(false);
  }

  async function deleteAgent(id: string) {
    try {
      await api.deleteAgent(id);
      const next = agents.filter((a) => a.id !== id);
      setAgents(next);
      if (draft?.id === id) setDraft(next[0] ? { ...next[0] } : null);
      setDelConfirm(null);
    } catch (e) { setError(`删除失败：${e}`); }
  }

  const cur = draft;

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Error banner */}
      {error && (
        <div style={{ background: "#FEF2F2", borderBottom: "1px solid #FECACA", padding: "8px 20px", display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          <span style={{ color: "#DC2626", fontSize: 12, flex: 1 }}>{error}</span>
          <button onClick={() => setError(null)} style={{ background: "none", border: "none", color: "#DC2626", cursor: "pointer", fontSize: 14, lineHeight: 1 }}>✕</button>
        </div>
      )}
      {/* Toast */}
      {toast && (
        <div style={{ position: "fixed", bottom: 24, right: 24, background: "#1A1D23", color: "#fff", padding: "10px 18px", borderRadius: 10, fontSize: 12, zIndex: 200, boxShadow: "0 4px 16px rgba(0,0,0,0.2)" }}>
          {toast}
        </div>
      )}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* Detail (left, flex-1) */}
      <main style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {cur ? (
          <>
            {/* Header */}
            <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "20px 28px 16px", borderBottom: "1px solid #E2E5EA", flexShrink: 0 }}>
              <div style={{ width: 50, height: 50, borderRadius: 13, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 19, fontWeight: 800, flexShrink: 0, background: cur.color + "18", color: cur.color, border: `2px solid ${cur.color}55` }}>
                {cur.avatar}
              </div>
              <div style={{ flex: 1 }}>
                <input
                  value={cur.name}
                  onChange={(e) => upd({ name: e.target.value })}
                  style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "6px 12px", color: "#1A1D23", fontSize: 17, fontWeight: 700, fontFamily: "inherit", outline: "none", width: "100%", boxSizing: "border-box" }}
                />
                <div style={{ display: "flex", gap: 8, marginTop: 5, alignItems: "center" }}>
                  <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 99, letterSpacing: 0.5, fontWeight: 600, color: STATUS_META[String(cur.active)].color, background: STATUS_META[String(cur.active)].bg }}>
                    {STATUS_META[String(cur.active)].label}
                  </span>
                  <span style={{ fontSize: 10, color: "#C0C5CE" }}>{cur.tools.length} tools</span>
                </div>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  onClick={toggleActive}
                  style={{ fontSize: 12, padding: "7px 16px", borderRadius: 8, background: "transparent", border: `1px solid ${cur.active ? "#F59E0B44" : "#10B98144"}`, cursor: "pointer", fontFamily: "inherit", color: cur.active ? "#F59E0B" : "#10B981" }}
                >
                  {cur.active ? "⏸ 暂停" : "▶ 启动"}
                </button>
                <button onClick={save} style={{ fontSize: 12, padding: "7px 16px", borderRadius: 8, background: "transparent", border: `1px solid ${dirty ? "#F59E0B" : cur.color}`, cursor: "pointer", fontFamily: "inherit", color: dirty ? "#F59E0B" : cur.color }}>
                  {dirty ? "● 保存" : "保存"}
                </button>
              </div>
            </div>

            {/* Meta + Body */}
            <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
              {/* Top metadata (L1+L2) */}
              <div style={{ borderBottom: "1px solid #E8EAED", overflowY: "auto", padding: "0 28px", flexShrink: 0, maxHeight: "52%" }}>
                {/* L1 */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "14px 0 0" }}>
                  <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4, background: "#4F6EF711", color: "#4F6EF7", fontWeight: 700, letterSpacing: 1 }}>L1</span>
                  <span style={{ fontSize: 10, color: "#C0C5CE", letterSpacing: 1 }}>元数据</span>
                </div>
                <Section label="描述">
                  <textarea value={cur.description} rows={2} onChange={(e) => upd({ description: e.target.value })}
                    style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "12px 14px", color: "#374151", fontSize: 13, lineHeight: 1.65, fontFamily: "inherit", outline: "none", width: "100%", boxSizing: "border-box", resize: "vertical" }} />
                </Section>

                {/* L2 */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0 0" }}>
                  <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4, background: "#F59E0B11", color: "#F59E0B", fontWeight: 700, letterSpacing: 1 }}>L2</span>
                  <span style={{ fontSize: 10, color: "#C0C5CE", letterSpacing: 1 }}>按需加载元数据</span>
                </div>

                <Section label={`允许工具  ·  ${cur.tools.length}`}>
                  <ToolEditor tools={cur.tools} color={cur.color} onChange={(v) => upd({ tools: v })} availableTools={availableTools} />
                </Section>

                {/* 配置区 */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0 0" }}>
                  <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4, background: "#6B728011", color: "#6B7280", fontWeight: 700, letterSpacing: 1 }}>配置</span>
                  <span style={{ fontSize: 10, color: "#C0C5CE", letterSpacing: 1 }}>模型配置 · 行为选项</span>
                </div>

                <Section label="模型配置">
                  <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 16 }}>
                    <FieldBox label="Model">
                      <input
                        value={cur.model ?? ""}
                        onChange={(e) => upd({ model: e.target.value })}
                        placeholder={workerModel || "输入 model id…"}
                        style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "8px 12px", color: "#1A1D23", fontSize: 11, fontFamily: "inherit", outline: "none", width: "100%", boxSizing: "border-box" }}
                      />
                    </FieldBox>
                    <FieldBox label="Max Tokens">
                      <input value={cur.max_tokens} onChange={(e) => upd({ max_tokens: Number(e.target.value) })}
                        style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "8px 12px", color: "#1A1D23", fontSize: 12, fontFamily: "inherit", outline: "none", width: "100%", boxSizing: "border-box" }} />
                    </FieldBox>
                    <FieldBox label="Temperature">
                      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                        <input type="range" min="0" max="1" step="0.05" value={cur.temperature}
                          onChange={(e) => upd({ temperature: parseFloat(e.target.value) })}
                          style={{ flex: 1, accentColor: cur.color }} />
                        <span style={{ fontSize: 12, color: "#6B7280", fontFamily: "monospace" }}>{cur.temperature}</span>
                      </div>
                    </FieldBox>
                  </div>
                </Section>

                <Section label="行为选项" last>
                  <div style={{ display: "flex", gap: 10 }}>
                    {[
                      { key: "allow_autonomous" as const, label: "自主决策", desc: "允许 Agent 自行判断下一步行动" },
                      { key: "enable_critic"    as const, label: "启用评审", desc: "执行后由 critic 节点自检结果质量" },
                    ].map((opt) => {
                      const on = cur[opt.key];
                      return (
                        <div key={opt.key} style={{ display: "flex", alignItems: "center", gap: 12, flex: 1, padding: "10px 14px", borderRadius: 8, background: on ? cur.color + "0A" : "#FFFFFF", border: `1px solid ${on ? cur.color + "33" : "#E2E5EA"}`, transition: "all 0.2s" }}>
                          <div style={{ flex: 1 }}>
                            <div style={{ fontSize: 12, color: on ? "#1A1D23" : "#6B7280", fontWeight: 600, marginBottom: 2 }}>{opt.label}</div>
                            <div style={{ fontSize: 10, color: "#C0C5CE", lineHeight: 1.4 }}>{opt.desc}</div>
                          </div>
                          <button onClick={() => upd({ [opt.key]: !on })}
                            style={{ width: 36, height: 20, borderRadius: 99, border: "none", cursor: "pointer", background: on ? cur.color : "#E2E5EA", position: "relative", flexShrink: 0, transition: "background 0.2s" }}>
                            <span style={{ position: "absolute", top: 2, left: on ? 18 : 2, width: 16, height: 16, borderRadius: "50%", background: "#fff", transition: "left 0.2s", display: "block" }} />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </Section>

              </div>

              {/* Bottom L3 body */}
              <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
                <div style={{ display: "flex", alignItems: "center", padding: "0 28px", borderBottom: "1px solid #E8EAED", flexShrink: 0 }}>
                  <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4, background: "#10B98111", color: "#10B981", fontWeight: 700, letterSpacing: 1, marginRight: 8 }}>L3</span>
                  {(["edit","preview"] as const).map((t) => (
                    <button key={t} onClick={() => setBodyTab(t)}
                      style={{ padding: "11px 16px", background: "transparent", border: "none", borderBottom: `2px solid ${bodyTab === t ? cur.color : "transparent"}`, color: bodyTab === t ? cur.color : "#9BA3AF", fontSize: 11, letterSpacing: 1, cursor: "pointer", fontFamily: "inherit", textTransform: "uppercase" }}>
                      {t === "edit" ? "✎ 编辑" : "◉ 预览"}
                    </button>
                  ))}
                  <span style={{ marginLeft: "auto", fontSize: 10, color: "#C0C5CE" }}>Markdown</span>
                </div>
                <div style={{ flex: 1, overflow: "hidden" }}>
                  {bodyTab === "edit"
                    ? <MarkdownEditor value={cur.content} onChange={(v) => upd({ content: v })} />
                    : <MarkdownPreview content={cur.content} style={{ padding: "20px 28px", overflowY: "auto", height: "100%", boxSizing: "border-box" }} />
                  }
                </div>
              </div>
            </div>
          </>
        ) : (
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "#E2E5EA", fontSize: 13 }}>
            {loading ? "加载中…" : "选择一个 Agent 查看详情"}
          </div>
        )}
      </main>

      {/* Agent List (right, 232px, order:2) */}
      <aside style={{ width: 232, background: "#FFFFFF", borderLeft: "1px solid #E2E5EA", display: "flex", flexDirection: "column", flexShrink: 0, order: 2 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "16px 14px 12px", borderBottom: "1px solid #E2E5EA" }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: "#1A1D23", flex: 1 }}>Agents</span>
          <span style={{ fontSize: 10, color: "#9BA3AF", background: "#E2E5EA", padding: "2px 7px", borderRadius: 99 }}>{agents.length}</span>
          <button onClick={scanAgents} disabled={scanning} title="扫描 workspace/agents/ 注册新文件"
            style={{ fontSize: 11, width: 28, height: 28, borderRadius: 7, background: "#7C3AED18", border: "1px solid #7C3AED44", color: "#7C3AED", cursor: scanning ? "wait" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", opacity: scanning ? 0.5 : 1 }}>
            ↑
          </button>
          <button onClick={() => setShowNew(true)}
            style={{ fontSize: 13, width: 28, height: 28, borderRadius: 7, background: "#4F6EF718", border: "1px solid #4F6EF744", color: "#4F6EF7", cursor: "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center" }}>
            ＋
          </button>
        </div>
        <div style={{ flex: 1, overflowY: "auto" }}>
          {loading && agents.length === 0 && <div style={{ padding: "16px", fontSize: 11, color: "#9BA3AF", textAlign: "center" }}>加载中…</div>}
          {agents.map((ag) => {
            const isSel = draft?.id === ag.id;
            const stLabel = ag.active ? "在线" : "已停用";
            const stColor = ag.active ? "#10B981" : "#6B7280";
            const stBg = ag.active ? "#10B98118" : "#6B728018";
            return (
              <div key={ag.id} onClick={() => { setDraft({ ...ag }); setBodyTab("preview"); setDirty(false); }}
                style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px 10px 14px", cursor: "pointer", transition: "background 0.12s", borderRight: `3px solid ${isSel ? ag.color : "transparent"}`, background: isSel ? "#F4F5F7" : "transparent" }}>
                <div style={{ width: 34, height: 34, borderRadius: 9, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 700, flexShrink: 0, background: ag.color + "22", color: ag.color, border: `1px solid ${ag.color}44` }}>
                  {ag.avatar}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: "#1A1D23", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ag.name}</div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 5 }}>
                  <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 99, letterSpacing: 0.5, fontWeight: 600, color: stColor, background: stBg }}>
                    {stLabel}
                  </span>
                  <div style={{ display: "flex", gap: 2 }} onClick={(e) => e.stopPropagation()}>
                    <button style={{ background: "transparent", border: "none", cursor: "pointer", fontSize: 11, padding: "1px 3px", fontFamily: "inherit", color: "#EF4444", opacity: 0.75 }}
                      onClick={() => setDelConfirm(ag.id)}>✕</button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </aside>

      {/* New Agent Modal */}
      {showNew && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.2)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
          <div style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 14, width: "100%", maxWidth: 480, boxShadow: "0 24px 64px rgba(0,0,0,0.1)" }}>
            <div style={{ display: "flex", alignItems: "center", padding: "16px 24px", borderBottom: "1px solid #E2E5EA" }}>
              <span style={{ flex: 1, fontSize: 14, fontWeight: 700, color: "#1A1D23" }}>新建 Agent</span>
              <button onClick={() => setShowNew(false)} style={{ background: "transparent", border: "none", color: "#9BA3AF", cursor: "pointer", fontSize: 14, fontFamily: "inherit" }}>✕</button>
            </div>
            <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 16 }}>
              <FieldBox label="名称">
                <input value={newForm.name} onChange={(e) => setNewForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="e.g. audit-analyst"
                  style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "8px 12px", color: "#1A1D23", fontSize: 12, fontFamily: "inherit", outline: "none", width: "100%", boxSizing: "border-box" }} />
              </FieldBox>
              <FieldBox label="描述">
                <input value={newForm.desc} onChange={(e) => setNewForm((f) => ({ ...f, desc: e.target.value }))}
                  placeholder="简要描述该 Agent 的职责…"
                  style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "8px 12px", color: "#1A1D23", fontSize: 12, fontFamily: "inherit", outline: "none", width: "100%", boxSizing: "border-box" }} />
              </FieldBox>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, padding: "14px 24px", borderTop: "1px solid #E2E5EA" }}>
              <button onClick={() => setShowNew(false)} style={{ fontSize: 12, padding: "7px 16px", borderRadius: 8, background: "transparent", border: "1px solid #E2E5EA", color: "#6B7280", cursor: "pointer", fontFamily: "inherit" }}>取消</button>
              <button onClick={createAgent} style={{ fontSize: 12, padding: "8px 18px", borderRadius: 8, background: "#4F6EF718", border: "1px solid #4F6EF744", color: "#4F6EF7", cursor: "pointer", fontFamily: "inherit", opacity: newForm.name.trim() ? 1 : 0.4 }}>
                创建 Agent
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirm */}
      {delConfirm && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.2)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
          <div style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 14, width: "100%", maxWidth: 360, boxShadow: "0 24px 64px rgba(0,0,0,0.1)" }}>
            <div style={{ display: "flex", alignItems: "center", padding: "16px 24px", borderBottom: "1px solid #E2E5EA" }}>
              <span style={{ flex: 1, fontSize: 14, fontWeight: 700, color: "#EF4444" }}>确认删除</span>
              <button onClick={() => setDelConfirm(null)} style={{ background: "transparent", border: "none", color: "#9BA3AF", cursor: "pointer", fontSize: 14, fontFamily: "inherit" }}>✕</button>
            </div>
            <div style={{ padding: "20px 24px" }}>
              <p style={{ margin: 0, fontSize: 13, color: "#6B7280", lineHeight: 1.7 }}>
                你正在删除 <strong style={{ color: "#1A1D23" }}>{agents.find((a) => a.id === delConfirm)?.name}</strong>。<br />
                此操作不可撤销，所有配置将被移除。
              </p>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, padding: "14px 24px", borderTop: "1px solid #E2E5EA" }}>
              <button onClick={() => setDelConfirm(null)} style={{ fontSize: 12, padding: "7px 16px", borderRadius: 8, background: "transparent", border: "1px solid #E2E5EA", color: "#6B7280", cursor: "pointer", fontFamily: "inherit" }}>取消</button>
              <button onClick={() => deleteAgent(delConfirm)} style={{ fontSize: 12, padding: "8px 18px", borderRadius: 8, background: "#EF444418", border: "1px solid #EF4444", color: "#EF4444", cursor: "pointer", fontFamily: "inherit" }}>
                确认删除
              </button>
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
  );
}

function Section({ label, children, last }: { label: string; children: React.ReactNode; last?: boolean }) {
  return (
    <div style={{ padding: "18px 0", borderBottom: last ? "none" : "1px solid #E8EAED", display: "flex", flexDirection: "column", gap: 10 }}>
      <span style={{ fontSize: 10, color: "#9BA3AF", letterSpacing: 2, textTransform: "uppercase" }}>{label}</span>
      {children}
    </div>
  );
}

function FieldBox({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{ fontSize: 10, color: "#C0C5CE", letterSpacing: 1 }}>{label}</span>
      {children}
    </div>
  );
}

const TOOL_CATEGORY_LABELS: Record<string, string> = {
  exec: "执行", file: "文件", skill: "技能", knowledge: "知识", mcp: "MCP",
};

function ToolEditor({ tools, color, onChange, availableTools }: { tools: string[]; color: string; onChange: (v: string[]) => void; availableTools: { name: string; category: string }[] }) {
  const groups: Record<string, string[]> = {};
  for (const t of availableTools) {
    if (!groups[t.category]) groups[t.category] = [];
    groups[t.category].push(t.name);
  }
  const order = ["exec", "file", "skill", "knowledge", "mcp"];
  const cats = Object.keys(groups).sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {cats.map((cat) => (
        <div key={cat}>
          <div style={{ fontSize: 10, color: "#C0C5CE", letterSpacing: 1, marginBottom: 5 }}>{TOOL_CATEGORY_LABELS[cat] ?? cat}</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {groups[cat].map((t) => {
              const on = tools.includes(t);
              return (
                <button key={t} onClick={() => onChange(on ? tools.filter((x) => x !== t) : [...tools, t])}
                  style={{ fontSize: 11, padding: "4px 10px", borderRadius: 6, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s", border: `1px solid ${on ? color : "#E2E5EA"}`, background: on ? color + "22" : "#FFFFFF", color: on ? color : "#9BA3AF" }}>
                  {t}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
