import { useState, useEffect, useCallback } from "react";
import { api, type SuiteSkill } from "@/shared/lib/api";
import { MarkdownPreview } from "@/shared/components/MarkdownPreview";
import { MarkdownEditor } from "@/shared/components/MarkdownEditor";



const STATUS_META: Record<string, { label: string; color: string; bg: string }> = {
  true:     { label: "在线",   color: "#10B981", bg: "#10B98118" },
  false:    { label: "已停用", color: "#6B7280", bg: "#6B728018" },
};

const COLORS = ["#F59E0B","#3B82F6","#10B981","#8B5CF6","#EC4899","#EF4444","#4F6EF7"];

function skillColor(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return COLORS[h % COLORS.length];
}

type SkillLocal = SuiteSkill & {
  color: string;
  avatar: string;
  argument_hint: string;
};

function toLocal(s: SuiteSkill): SkillLocal {
  return {
    ...s,
    color:         skillColor(s.id),
    avatar:        s.name ? s.name[0].toUpperCase() : "S",
    argument_hint: s.argument_hint ?? "",
  };
}


export function SkillPage() {
  const [skills, setSkills] = useState<SkillLocal[]>([]);
  const [draft, setDraft] = useState<SkillLocal | null>(null);
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
      const raw = await api.listSkills();
      const locals = raw.map(toLocal);
      setSkills(locals);
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
    api.listTools().then((list) => setAvailableTools(list)).catch(() => {});
  }, []);

  const upd = (patch: Partial<SkillLocal>) => { setDraft((d) => d ? { ...d, ...patch } : d); setDirty(true); };

  async function save() {
    if (!draft) return;
    try {
      await api.updateSkill(draft.id, {
        description:    draft.description,
        content:        draft.content,
        allowed_tools:  draft.allowed_tools,
        model:          draft.model ?? undefined,
        active:         draft.active,
        triggers:       draft.triggers,
        patterns:       draft.patterns,
        contexts:       draft.contexts,
        priority:       draft.priority,
        argument_hint:  draft.argument_hint,
      });
      setSkills((p) => p.map((sk) => sk.id === draft.id ? draft : sk));
      setDirty(false);
      showToast("已保存");
    } catch (e) { setError(`保存失败：${e}`); }
  }

  async function toggleActive() {
    if (!draft) return;
    const newActive = !draft.active;
    upd({ active: newActive });
    try {
      await api.updateSkill(draft.id, { active: newActive });
      setSkills((p) => p.map((sk) => sk.id === draft.id ? { ...sk, active: newActive } : sk));
      showToast(newActive ? "已启用" : "已停用");
    } catch (e) {
      upd({ active: !newActive });
      setError(`操作失败：${e}`);
    }
  }

  async function createSkill() {
    if (!newForm.name.trim()) return;
    const md = `---\nname: ${newForm.name.trim()}\ndescription: ${newForm.desc}\nstatus: idle\n---\n\n## 功能说明\n\n${newForm.desc || "在此描述技能的工作流程。"}`;
    try {
      const sk = await api.registerSkill(md);
      await load();
      const local = toLocal(sk);
      setDraft({ ...local });
      setShowNew(false);
      setNewForm({ name: "", desc: "" });
    } catch (e) { setError(`创建失败：${e}`); }
  }

  async function scanSkills() {
    setScanning(true);
    try {
      const { registered, skipped } = await api.scanSkills();
      const raw = await api.listSkills();
      const locals = raw.map(toLocal);
      setSkills(locals);
      setDraft((prev) => {
        if (!prev) return locals[0] ? { ...locals[0] } : null;
        const refreshed = locals.find((sk) => sk.id === prev.id);
        return refreshed ? { ...refreshed } : prev;
      });
      setDirty(false);
      showToast(registered > 0
        ? `已注册 ${registered} 个 Skill${skipped > 0 ? `，${skipped} 个跳过` : ""}`
        : "workspace/skills/ 中没有新的 Skill 需要注册");
    } catch (e) { setError(`扫描失败：${e}`); }
    setScanning(false);
  }

  async function deleteSkill(id: string) {
    try {
      await api.deleteSkill(id);
      const next = skills.filter((sk) => sk.id !== id);
      setSkills(next);
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
              <div style={{ width: 50, height: 50, borderRadius: 13, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 19, fontWeight: 800, flexShrink: 0, background: cur.color + "18", color: cur.color, border: `2px solid ${cur.color}44` }}>
                {cur.avatar}
              </div>
              <div style={{ flex: 1 }}>
                <input value={cur.name} onChange={(e) => upd({ name: e.target.value })}
                  style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "6px 12px", color: "#1A1D23", fontSize: 17, fontWeight: 700, fontFamily: "inherit", outline: "none", width: "100%", boxSizing: "border-box" }} />
                <div style={{ display: "flex", gap: 8, marginTop: 5, alignItems: "center" }}>
                  <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 99, letterSpacing: 0.5, fontWeight: 600, color: STATUS_META[String(cur.active)].color, background: STATUS_META[String(cur.active)].bg }}>
                    {STATUS_META[String(cur.active)].label}
                  </span>
                  <span style={{ fontSize: 10, color: "#C0C5CE" }}>{cur.allowed_tools.length} tools</span>
                </div>
              </div>
              <button onClick={toggleActive} style={{ fontSize: 12, padding: "7px 16px", borderRadius: 8, background: "transparent", border: `1px solid ${cur.active ? "#F59E0B44" : "#10B98144"}`, cursor: "pointer", fontFamily: "inherit", color: cur.active ? "#F59E0B" : "#10B981" }}>
                {cur.active ? "⏸ 停用" : "▶ 启用"}
              </button>
              <button onClick={save} style={{ fontSize: 12, padding: "7px 16px", borderRadius: 8, background: "transparent", border: `1px solid ${dirty ? "#F59E0B" : cur.color}`, cursor: "pointer", fontFamily: "inherit", color: dirty ? "#F59E0B" : cur.color }}>
                {dirty ? "● 保存" : "保存"}
              </button>
            </div>

            {/* Meta + Body */}
            <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
              {/* Top L1 + L2 */}
              <div style={{ borderBottom: "1px solid #E8EAED", overflowY: "auto", padding: "0 28px", flexShrink: 0, maxHeight: "48%" }}>
                {/* L1 */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "14px 0 0" }}>
                  <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4, background: "#4F6EF711", color: "#4F6EF7", fontWeight: 700, letterSpacing: 1 }}>L1</span>
                  <span style={{ fontSize: 10, color: "#C0C5CE", letterSpacing: 1 }}>元数据</span>
                </div>
                <Section label="描述">
                  <textarea value={cur.description} rows={2} onChange={(e) => upd({ description: e.target.value })}
                    style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "12px 14px", color: "#374151", fontSize: 13, lineHeight: 1.65, fontFamily: "inherit", outline: "none", width: "100%", boxSizing: "border-box", resize: "vertical" }} />
                </Section>
                <Section label="触发词 Triggers">
                  <TagEditor tags={cur.triggers ?? []} color="#4F6EF7" onChange={(v) => upd({ triggers: v })} placeholder="输入关键词 Enter 确认" />
                </Section>
                <Section label="正则模式 Patterns  ·  权重 0.4">
                  <TagEditor tags={cur.patterns ?? []} color="#F59E0B" onChange={(v) => upd({ patterns: v })} placeholder="输入正则表达式 Enter 确认" />
                </Section>
                <Section label="上下文特征 Contexts  ·  权重 0.3">
                  <TagEditor tags={cur.contexts ?? []} color="#10B981" onChange={(v) => upd({ contexts: v })} placeholder="如 k8s_environment Enter 确认" />
                </Section>
                <Section label="优先级 Priority">
                  <input type="number" min={0} max={10} value={cur.priority ?? 0} onChange={(e) => upd({ priority: Number(e.target.value) })}
                    style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "8px 12px", color: "#1A1D23", fontSize: 12, fontFamily: "inherit", outline: "none", width: 100 }} />
                  <span style={{ fontSize: 10, color: "#C0C5CE" }}>内置 Skill 建议 8-10，磁盘 Skill 默认 0</span>
                </Section>

                {/* L2 */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0 0" }}>
                  <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 4, background: "#F59E0B11", color: "#F59E0B", fontWeight: 700, letterSpacing: 1 }}>L2</span>
                  <span style={{ fontSize: 10, color: "#C0C5CE", letterSpacing: 1 }}>按需加载</span>
                </div>

                <Section label="调用参数说明 argument_hint">
                  <input
                    value={cur.argument_hint ?? ""}
                    onChange={(e) => upd({ argument_hint: e.target.value })}
                    placeholder="如：target=目标URL, depth=扫描深度"
                    style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "8px 12px", color: "#1A1D23", fontSize: 11, fontFamily: "inherit", outline: "none", width: "100%", boxSizing: "border-box" }}
                  />
                </Section>

                <Section label={`Tools  ·  ${cur.allowed_tools.length}`} last>
                  <ToolEditor tools={cur.allowed_tools} color={cur.color} onChange={(v) => upd({ allowed_tools: v })} availableTools={availableTools} />
                </Section>

                {/* 配置 */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0 0" }}>
                  <span style={{ fontSize: 10, color: "#C0C5CE", letterSpacing: 1 }}>配置</span>
                </div>

                <Section label="模型" last>
                  <input
                    value={cur.model ?? ""}
                    onChange={(e) => upd({ model: e.target.value })}
                    placeholder={workerModel ? `默认：${workerModel}` : "输入 model id，留空继承默认"}
                    style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "8px 12px", color: "#1A1D23", fontSize: 11, fontFamily: "inherit", outline: "none", width: "280px", boxSizing: "border-box" }}
                  />
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
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "#C0C5CE", fontSize: 13 }}>
            {loading ? "加载中…" : "选择一个 Skill 查看详情"}
          </div>
        )}
      </main>

      {/* Skill List (right, 232px) */}
      <aside style={{ width: 232, background: "#FFFFFF", borderLeft: "1px solid #E2E5EA", display: "flex", flexDirection: "column", flexShrink: 0, order: 2 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "16px 14px 12px", borderBottom: "1px solid #E2E5EA" }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: "#1A1D23", flex: 1 }}>Skills</span>
          <span style={{ fontSize: 10, color: "#9BA3AF", background: "#E2E5EA", padding: "2px 7px", borderRadius: 99 }}>{skills.length}</span>
          <button onClick={scanSkills} disabled={scanning} title="扫描 workspace/skills/ 注册新文件"
            style={{ fontSize: 11, width: 28, height: 28, borderRadius: 7, background: "#7C3AED18", border: "1px solid #7C3AED44", color: "#7C3AED", cursor: scanning ? "wait" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", opacity: scanning ? 0.5 : 1 }}>
            ↑
          </button>
          <button onClick={() => setShowNew(true)}
            style={{ fontSize: 13, width: 28, height: 28, borderRadius: 7, background: "#4F6EF718", border: "1px solid #4F6EF744", color: "#4F6EF7", cursor: "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center" }}>
            ＋
          </button>
        </div>
        <div style={{ flex: 1, overflowY: "auto" }}>
          {loading && skills.length === 0 && <div style={{ padding: "16px", fontSize: 11, color: "#9BA3AF", textAlign: "center" }}>加载中…</div>}
          {skills.map((sk) => {
            const isSel = draft?.id === sk.id;
            const stLabel = sk.active ? "在线" : "已停用";
            const stColor = sk.active ? "#10B981" : "#6B7280";
            const stBg = sk.active ? "#10B98118" : "#6B728018";
            return (
              <div key={sk.id} onClick={() => { setDraft({ ...sk }); setBodyTab("preview"); setDirty(false); }}
                style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px 10px 14px", cursor: "pointer", transition: "background 0.12s", borderRight: `3px solid ${isSel ? sk.color : "transparent"}`, background: isSel ? "#F4F5F7" : "transparent" }}>
                <div style={{ width: 34, height: 34, borderRadius: 9, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 700, flexShrink: 0, background: sk.color + "18", color: sk.color, border: `1px solid ${sk.color}44` }}>
                  {sk.avatar}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: "#1A1D23", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sk.name}</div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 5 }}>
                  <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 99, letterSpacing: 0.5, fontWeight: 600, color: stColor, background: stBg }}>{stLabel}</span>
                  <div style={{ display: "flex", gap: 2 }} onClick={(e) => e.stopPropagation()}>
                    <button style={{ background: "transparent", border: "none", cursor: "pointer", fontSize: 11, padding: "1px 3px", fontFamily: "inherit", color: "#EF4444", opacity: 0.75 }}
                      onClick={() => setDelConfirm(sk.id)}>✕</button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </aside>

      {/* New Skill Modal */}
      {showNew && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.2)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
          <div style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 14, width: "100%", maxWidth: 480, boxShadow: "0 24px 64px rgba(0,0,0,0.1)" }}>
            <div style={{ display: "flex", alignItems: "center", padding: "16px 24px", borderBottom: "1px solid #E2E5EA" }}>
              <span style={{ flex: 1, fontSize: 14, fontWeight: 700, color: "#1A1D23" }}>新建 Skill</span>
              <button onClick={() => setShowNew(false)} style={{ background: "transparent", border: "none", color: "#9BA3AF", cursor: "pointer", fontSize: 14, fontFamily: "inherit" }}>✕</button>
            </div>
            <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 16 }}>
              <FieldBox label="名称">
                <input value={newForm.name} onChange={(e) => setNewForm((f) => ({ ...f, name: e.target.value }))} placeholder="e.g. java-audit"
                  style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "8px 12px", color: "#1A1D23", fontSize: 12, fontFamily: "inherit", outline: "none", width: "100%", boxSizing: "border-box" }} />
              </FieldBox>
              <FieldBox label="描述">
                <input value={newForm.desc} onChange={(e) => setNewForm((f) => ({ ...f, desc: e.target.value }))} placeholder="简要描述该 Skill 的功能…"
                  style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "8px 12px", color: "#1A1D23", fontSize: 12, fontFamily: "inherit", outline: "none", width: "100%", boxSizing: "border-box" }} />
              </FieldBox>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, padding: "14px 24px", borderTop: "1px solid #E2E5EA" }}>
              <button onClick={() => setShowNew(false)} style={{ fontSize: 12, padding: "7px 16px", borderRadius: 8, background: "transparent", border: "1px solid #E2E5EA", color: "#6B7280", cursor: "pointer", fontFamily: "inherit" }}>取消</button>
              <button onClick={createSkill} style={{ fontSize: 12, padding: "8px 18px", borderRadius: 8, background: "#4F6EF718", border: "1px solid #4F6EF744", color: "#4F6EF7", cursor: "pointer", fontFamily: "inherit", opacity: newForm.name.trim() ? 1 : 0.4 }}>
                创建 Skill
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
                你正在删除 <strong style={{ color: "#1A1D23" }}>{skills.find((sk) => sk.id === delConfirm)?.name}</strong>。<br />
                此操作不可撤销，所有配置将被移除。
              </p>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, padding: "14px 24px", borderTop: "1px solid #E2E5EA" }}>
              <button onClick={() => setDelConfirm(null)} style={{ fontSize: 12, padding: "7px 16px", borderRadius: 8, background: "transparent", border: "1px solid #E2E5EA", color: "#6B7280", cursor: "pointer", fontFamily: "inherit" }}>取消</button>
              <button onClick={() => deleteSkill(delConfirm)} style={{ fontSize: 12, padding: "8px 18px", borderRadius: 8, background: "#EF444411", border: "1px solid #EF4444", color: "#EF4444", cursor: "pointer", fontFamily: "inherit" }}>
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

function TagEditor({ tags, color, onChange, placeholder }: { tags: string[]; color: string; onChange: (v: string[]) => void; placeholder?: string }) {
  const [input, setInput] = useState("");
  function commit() {
    const val = input.trim();
    if (val && !tags.includes(val)) onChange([...tags, val]);
    setInput("");
  }
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
      {tags.map((t) => (
        <span key={t} style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, padding: "3px 8px", borderRadius: 6, background: color + "18", border: `1px solid ${color}44`, color }}>
          {t}
          <button onClick={() => onChange(tags.filter((x) => x !== t))}
            style={{ background: "none", border: "none", cursor: "pointer", color, fontSize: 11, padding: 0, lineHeight: 1, opacity: 0.7 }}>✕</button>
        </span>
      ))}
      <input value={input} onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }}
        onBlur={commit}
        placeholder={placeholder}
        style={{ border: "1px dashed #E2E5EA", borderRadius: 6, padding: "3px 8px", fontSize: 11, color: "#374151", fontFamily: "inherit", outline: "none", background: "transparent", minWidth: 160 }} />
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
