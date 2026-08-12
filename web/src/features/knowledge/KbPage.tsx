import { useState, useEffect, useCallback } from "react";
import { api, type KnowledgeEntry } from "@/shared/lib/api";
import { MarkdownPreview } from "@/shared/components/MarkdownPreview";
import { MarkdownEditor } from "@/shared/components/MarkdownEditor";

export function KbPage() {
  const [articles, setArticles] = useState<KnowledgeEntry[]>([]);
  const [draft, setDraft] = useState<KnowledgeEntry | null>(null);
  const [bodyTab, setBodyTab] = useState<"edit" | "preview">("preview");
  const [tagInput, setTagInput] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [delConfirm, setDelConfirm] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [newForm, setNewForm] = useState<{ name: string; tags: string[]; tagInput: string }>({ name: "", tags: [], tagInput: "" });
  const [dirty, setDirty] = useState(false);
  const [search, setSearch] = useState("");
  const [filterTag, setFilterTag] = useState("");

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(null), 3000); };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const raw = await api.listKnowledge();
      setArticles(raw);
      // 用函数式更新避免 draft 成为依赖项（stale closure 修复）
      setDraft((prev) => prev ?? (raw.length > 0 ? { ...raw[0] } : null));
    } catch (e) {
      setError(`加载失败：${e}`);
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const upd = (patch: Partial<KnowledgeEntry>) => { setDraft((d) => d ? { ...d, ...patch } : d); setDirty(true); };

  function addTag() {
    const v = tagInput.trim().toLowerCase().replace(/\s+/g, "-");
    if (!v || (draft?.tags ?? []).includes(v)) return;
    upd({ tags: [...(draft?.tags ?? []), v] });
    setTagInput("");
  }

  async function save() {
    if (!draft) return;
    try {
      await api.updateKnowledge(draft.id, {
        name: draft.name, content: draft.content, tags: draft.tags,
      });
      setArticles((p) => p.map((a) => a.id === draft.id ? draft : a));
      setDirty(false);
      showToast("已保存");
    } catch (e) { setError(`保存失败：${e}`); }
  }

  async function createArticle() {
    if (!newForm.name.trim()) return;
    try {
      const entry = await api.registerKnowledge({
        name: newForm.name.trim(),
        title: newForm.name.trim(),
        category: "general",
        content: `## ${newForm.name}\n\n在此编写知识内容。`,
        tags: newForm.tags,
      });
      await load();
      setDraft({ ...entry });
      setShowNew(false);
      setNewForm({ name: "", tags: [], tagInput: "" });
    } catch (e) { setError(`创建失败：${e}`); }
  }

  async function scanKnowledge() {
    setScanning(true);
    try {
      const { registered, skipped } = await api.scanKnowledge();
      await load();
      showToast(registered > 0
        ? `已注册 ${registered} 篇文章${skipped > 0 ? `，${skipped} 个跳过` : ""}`
        : "workspace/knowledge/ 中没有新文章需要注册");
    } catch (e) { setError(`扫描失败：${e}`); }
    setScanning(false);
  }

  async function deleteArticle(id: string) {
    try {
      await api.deleteKnowledge(id);
      const next = articles.filter((a) => a.id !== id);
      setArticles(next);
      if (draft?.id === id) setDraft(next[0] ? { ...next[0] } : null);
      setDelConfirm(null);
    } catch (e) { setError(`删除失败：${e}`); }
  }

  const cur = draft;

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {error && (
        <div style={{ background: "#FEF2F2", borderBottom: "1px solid #FECACA", padding: "8px 20px", display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          <span style={{ color: "#DC2626", fontSize: 12, flex: 1 }}>{error}</span>
          <button onClick={() => setError(null)} style={{ background: "none", border: "none", color: "#DC2626", cursor: "pointer", fontSize: 14, lineHeight: 1 }}>✕</button>
        </div>
      )}
      {toast && (
        <div style={{ position: "fixed", bottom: 24, right: 24, background: "#1A1D23", color: "#fff", padding: "10px 18px", borderRadius: 10, fontSize: 12, zIndex: 200, boxShadow: "0 4px 16px rgba(0,0,0,0.2)" }}>
          {toast}
        </div>
      )}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* Article Detail (left, flex-1) */}
      <main style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {cur ? (
          <>
            {/* Header with name + tags */}
            <div style={{ display: "flex", flexDirection: "column", alignItems: "stretch", gap: 10, padding: "20px 32px 14px", borderBottom: "1px solid #E2E5EA", flexShrink: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <input value={cur.name} onChange={(e) => upd({ name: e.target.value })}
                  style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "6px 12px", color: "#1A1D23", fontSize: 17, fontWeight: 700, fontFamily: "inherit", outline: "none", flex: 1, boxSizing: "border-box" }} />
                <button onClick={save} style={{ fontSize: 12, padding: "7px 16px", borderRadius: 8, background: "transparent", border: `1px solid ${dirty ? "#F59E0B" : "#4F6EF7"}`, cursor: "pointer", fontFamily: "inherit", color: dirty ? "#F59E0B" : "#4F6EF7", flexShrink: 0 }}>
                  {dirty ? "● 保存" : "保存"}
                </button>
              </div>
              {/* Tags row */}
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                {(cur.tags ?? []).map((t) => (
                  <span key={t} style={{ fontSize: 11, padding: "2px 9px", borderRadius: 99, background: "#4F6EF711", border: "1px solid #4F6EF733", color: "#4F6EF7", display: "flex", alignItems: "center", gap: 4 }}>
                    #{t}
                    <button onClick={() => upd({ tags: (cur.tags ?? []).filter((x) => x !== t) })}
                      style={{ background: "none", border: "none", color: "#4F6EF799", cursor: "pointer", fontSize: 10, padding: 0, lineHeight: 1 }}>✕</button>
                  </span>
                ))}
                <input
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addTag()}
                  placeholder="+ 标签"
                  style={{ background: "transparent", border: "none", outline: "none", fontSize: 11, color: "#9BA3AF", fontFamily: "inherit", width: 60, cursor: "text" }}
                />
              </div>
            </div>

            {/* Body editor */}
            <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
              <div style={{ display: "flex", alignItems: "center", padding: "0 32px", borderBottom: "1px solid #E8EAED", flexShrink: 0 }}>
                {(["edit","preview"] as const).map((t) => (
                  <button key={t} onClick={() => setBodyTab(t)}
                    style={{ padding: "11px 16px", background: "transparent", border: "none", borderBottom: `2px solid ${bodyTab === t ? "#4F6EF7" : "transparent"}`, color: bodyTab === t ? "#4F6EF7" : "#9BA3AF", fontSize: 11, letterSpacing: 1, cursor: "pointer", fontFamily: "inherit", textTransform: "uppercase" }}>
                    {t === "edit" ? "✎ 编辑" : "◉ 预览"}
                  </button>
                ))}
                <span style={{ marginLeft: "auto", fontSize: 10, color: "#C0C5CE" }}>Markdown</span>
              </div>
              <div style={{ flex: 1, overflow: "hidden" }}>
                {bodyTab === "edit"
                  ? <MarkdownEditor value={cur.content} onChange={(v) => upd({ content: v })} style={{ padding: "28px 32px" }} />
                  : <MarkdownPreview content={cur.content} style={{ padding: "28px 32px", overflowY: "auto", height: "100%", boxSizing: "border-box" }} />
                }
              </div>
            </div>
          </>
        ) : (
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "#C0C5CE", fontSize: 13 }}>
            {loading ? "加载中…" : "选择一篇文章查看内容"}
          </div>
        )}
      </main>

      {/* Article List (right, 232px) */}
      <aside style={{ width: 232, background: "#FFFFFF", borderLeft: "1px solid #E2E5EA", display: "flex", flexDirection: "column", flexShrink: 0, order: 2 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "16px 14px 12px", borderBottom: "1px solid #E2E5EA" }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: "#1A1D23", flex: 1 }}>知识库</span>
          <span style={{ fontSize: 10, color: "#9BA3AF", background: "#E2E5EA", padding: "2px 7px", borderRadius: 99 }}>{articles.length}</span>
          <button onClick={scanKnowledge} disabled={scanning} title="扫描 workspace/knowledge/ 注册新文件"
            style={{ fontSize: 11, width: 28, height: 28, borderRadius: 7, background: "#7C3AED18", border: "1px solid #7C3AED44", color: "#7C3AED", cursor: scanning ? "wait" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", opacity: scanning ? 0.5 : 1 }}>
            ↑
          </button>
          <button onClick={() => setShowNew(true)}
            style={{ fontSize: 13, width: 28, height: 28, borderRadius: 7, background: "#4F6EF718", border: "1px solid #4F6EF744", color: "#4F6EF7", cursor: "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center" }}>
            ＋
          </button>
        </div>
        <div style={{ padding: "8px 10px 6px" }}>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索…"
            style={{ width: "100%", boxSizing: "border-box", background: "#F0F1F3", border: "none", borderRadius: 6, padding: "5px 9px", fontSize: 11, color: "#374151", fontFamily: "inherit", outline: "none" }}
          />
          {filterTag && (
            <span onClick={() => setFilterTag("")} style={{ display: "inline-flex", alignItems: "center", gap: 4, marginTop: 6, fontSize: 9, padding: "2px 7px", borderRadius: 99, background: "#4F6EF722", border: "1px solid #4F6EF766", color: "#4F6EF7", cursor: "pointer" }}>
              #{filterTag} ✕
            </span>
          )}
        </div>
        <div style={{ flex: 1, overflowY: "auto" }}>
          {loading && articles.length === 0 && <div style={{ padding: "16px", fontSize: 11, color: "#9BA3AF", textAlign: "center" }}>加载中…</div>}
          {articles.filter((a) => {
            const matchSearch = !search || a.name.toLowerCase().includes(search.toLowerCase());
            const matchTag = !filterTag || (a.tags ?? []).includes(filterTag);
            return matchSearch && matchTag;
          }).map((a) => {
            const isSel = draft?.id === a.id;
            return (
              <div key={a.id} onClick={() => { setDraft({ ...a }); setDirty(false); setBodyTab("preview"); setTagInput(""); }}
                style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px 10px 14px", cursor: "pointer", transition: "background 0.12s", borderRight: `3px solid ${isSel ? "#4F6EF7" : "transparent"}`, background: isSel ? "#F4F5F7" : "transparent" }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: "#1A1D23", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name}</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
                    {(a.tags ?? []).slice(0, 3).map((t) => (
                      <span key={t} onClick={(e) => { e.stopPropagation(); setFilterTag(t === filterTag ? "" : t); }}
                        style={{ fontSize: 9, padding: "1px 6px", borderRadius: 99, background: t === filterTag ? "#4F6EF733" : "#4F6EF711", border: t === filterTag ? "1px solid #4F6EF7" : "1px solid transparent", color: "#4F6EF7", cursor: "pointer" }}>#{t}</span>
                    ))}
                  </div>
                </div>
                <button style={{ background: "transparent", border: "none", cursor: "pointer", fontSize: 11, padding: "1px 3px", fontFamily: "inherit", color: "#EF4444", opacity: 0.75, flexShrink: 0 }}
                  onClick={(e) => { e.stopPropagation(); setDelConfirm(a.id); }}>✕</button>
              </div>
            );
          })}
        </div>
      </aside>

      {/* New Article Modal */}
      {showNew && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.2)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
          <div style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 14, width: "100%", maxWidth: 480, boxShadow: "0 24px 64px rgba(0,0,0,0.1)" }}>
            <div style={{ display: "flex", alignItems: "center", padding: "16px 24px", borderBottom: "1px solid #E2E5EA" }}>
              <span style={{ flex: 1, fontSize: 14, fontWeight: 700, color: "#1A1D23" }}>新建文章</span>
              <button onClick={() => setShowNew(false)} style={{ background: "transparent", border: "none", color: "#9BA3AF", cursor: "pointer", fontSize: 14, fontFamily: "inherit" }}>✕</button>
            </div>
            <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 16 }}>
              <FieldBox label="名称">
                <input value={newForm.name} onChange={(e) => setNewForm((f) => ({ ...f, name: e.target.value }))} placeholder="e.g. ssrf-patterns"
                  style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "8px 12px", color: "#1A1D23", fontSize: 12, fontFamily: "inherit", outline: "none", width: "100%", boxSizing: "border-box" }} />
              </FieldBox>
              <FieldBox label="标签">
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 6 }}>
                  {newForm.tags.map((t) => (
                    <span key={t} style={{ fontSize: 11, padding: "2px 8px", borderRadius: 99, background: "#4F6EF711", border: "1px solid #4F6EF733", color: "#4F6EF7", display: "flex", alignItems: "center", gap: 4 }}>
                      #{t}
                      <button onClick={() => setNewForm((f) => ({ ...f, tags: f.tags.filter((x) => x !== t) }))}
                        style={{ background: "none", border: "none", color: "#4F6EF7", cursor: "pointer", fontSize: 10, padding: 0 }}>✕</button>
                    </span>
                  ))}
                </div>
                <input
                  value={newForm.tagInput ?? ""}
                  onChange={(e) => setNewForm((f) => ({ ...f, tagInput: e.target.value }))}
                  onKeyDown={(e) => {
                    if (e.key !== "Enter") return;
                    const v = (newForm.tagInput ?? "").trim().toLowerCase().replace(/\s+/g, "-");
                    if (v && !newForm.tags.includes(v)) setNewForm((f) => ({ ...f, tags: [...f.tags, v], tagInput: "" }));
                  }}
                  placeholder="输入后回车添加…"
                  style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "8px 12px", color: "#1A1D23", fontSize: 12, fontFamily: "inherit", outline: "none", width: "100%", boxSizing: "border-box" }}
                />
              </FieldBox>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, padding: "14px 24px", borderTop: "1px solid #E2E5EA" }}>
              <button onClick={() => setShowNew(false)} style={{ fontSize: 12, padding: "7px 16px", borderRadius: 8, background: "transparent", border: "1px solid #E2E5EA", color: "#6B7280", cursor: "pointer", fontFamily: "inherit" }}>取消</button>
              <button onClick={createArticle} style={{ fontSize: 12, padding: "8px 18px", borderRadius: 8, background: "#4F6EF718", border: "1px solid #4F6EF744", color: "#4F6EF7", cursor: "pointer", fontFamily: "inherit", opacity: newForm.name.trim() ? 1 : 0.4 }}>
                创建文章
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
                你正在删除 <strong style={{ color: "#1A1D23" }}>{articles.find((a) => a.id === delConfirm)?.name}</strong>，此操作不可撤销。
              </p>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, padding: "14px 24px", borderTop: "1px solid #E2E5EA" }}>
              <button onClick={() => setDelConfirm(null)} style={{ fontSize: 12, padding: "7px 16px", borderRadius: 8, background: "transparent", border: "1px solid #E2E5EA", color: "#6B7280", cursor: "pointer", fontFamily: "inherit" }}>取消</button>
              <button onClick={() => deleteArticle(delConfirm)} style={{ fontSize: 12, padding: "8px 18px", borderRadius: 8, background: "#EF444411", border: "1px solid #EF4444", color: "#EF4444", cursor: "pointer", fontFamily: "inherit" }}>
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

function FieldBox({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{ fontSize: 10, color: "#C0C5CE", letterSpacing: 1 }}>{label}</span>
      {children}
    </div>
  );
}
