import { useState, useEffect, useCallback } from "react";
import { api, type Container } from "@/shared/lib/api";
import { ModuleHeader, ModuleTitle } from "@/shared/components/ModuleHeader";

const CONTAINER_STATUS: Record<string, { label: string; color: string; bg: string }> = {
  running: { label: "运行中", color: "#10B981", bg: "#10B98115" },
  stopped: { label: "已停止", color: "#9BA3AF", bg: "#9BA3AF15" },
  created: { label: "已创建", color: "#4F6EF7",  bg: "#4F6EF715" },
  error:   { label: "异常",   color: "#EF4444",  bg: "#EF444415" },
};

const emptyForm = { name: "", image: "", ports: "", env_vars: "" };

export function ContainerPage() {
  const [containers, setContainers] = useState<Container[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionId, setActionId] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setContainers(await api.listContainers());
      setOffline(false);
    } catch {
      // 容器服务(harness/podman)可能未就绪；不覆盖已有列表，改用离线指示
      setOffline(true);
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleCreate() {
    if (!form.name.trim() || !form.image.trim()) return;
    try {
      await api.createContainer({
        name: form.name.trim(),
        image: form.image.trim(),
        ports: form.ports.split(",").map((p) => p.trim()).filter(Boolean),
        env_vars: form.env_vars.split(",").map((e) => e.trim()).filter(Boolean),
      });
      await load();
      setShowCreate(false);
      setForm(emptyForm);
    } catch (e) { setError(`创建失败：${e}`); }
  }

  async function handleToggle(c: Container) {
    setActionId(c.id);
    try {
      if (c.status === "running") await api.stopContainer(c.id);
      else await api.startContainer(c.id);
      await load();
    } catch (e) { setError(`操作失败：${e}`); }
    setActionId(null);
  }

  async function handleDelete(id: string) {
    if (deleteId === id) {
      try {
        await api.deleteContainer(id);
        await load();
        setDeleteId(null);
      } catch (e) { setError(`删除失败：${e}`); }
    } else {
      setDeleteId(id);
    }
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "#F4F5F7" }}>
      {/* Offline / error banners */}
      {offline && (
        <div style={{ background: "#FFFBEB", borderBottom: "1px solid #FDE68A", padding: "7px 20px", fontSize: 11, color: "#92400E", flexShrink: 0 }}>
          ⚠ 容器服务未响应，容器功能暂不可用
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
        title={<ModuleTitle>容器管理</ModuleTitle>}
        actions={<>
          <span style={{ fontSize: 11, color: "#9BA3AF" }}>
            {containers.filter((c) => c.status === "running").length} 运行中 · {containers.length} 总计
          </span>
          <button onClick={load} style={{ fontSize: 12, padding: "7px 14px", borderRadius: 8, background: "transparent", border: "1px solid #E2E5EA", color: "#6B7280", cursor: "pointer", fontFamily: "inherit" }}>
            刷新
          </button>
          <button onClick={() => setShowCreate(true)} style={{ fontSize: 12, padding: "8px 18px", borderRadius: 8, background: "#4F6EF718", border: "1px solid #4F6EF744", color: "#4F6EF7", cursor: "pointer", fontFamily: "inherit" }}>
            ＋ 新建容器
          </button>
        </>}
      />

      {/* Grid */}
      <div style={{ flex: 1, overflowY: "auto", padding: 24, display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(280px,1fr))", gap: 16, alignContent: "start" }}>
        {loading && containers.length === 0 && (
          <div style={{ gridColumn: "1/-1", textAlign: "center", padding: 40, fontSize: 13, color: "#9BA3AF" }}>加载中…</div>
        )}
        {!loading && containers.length === 0 && (
          <div style={{ gridColumn: "1/-1", textAlign: "center", padding: 60, fontSize: 13, color: "#9BA3AF" }}>
            暂无容器<br />
            <button onClick={() => setShowCreate(true)} style={{ marginTop: 12, fontSize: 12, padding: "7px 16px", borderRadius: 8, background: "#4F6EF718", border: "1px solid #4F6EF744", color: "#4F6EF7", cursor: "pointer", fontFamily: "inherit" }}>
              新建容器
            </button>
          </div>
        )}
        {containers.map((c) => {
          const st = CONTAINER_STATUS[c.status] ?? CONTAINER_STATUS.stopped;
          const running = c.status === "running";
          const isAction = actionId === c.id;
          const confirming = deleteId === c.id;
          const managed = c.managed !== false;
          return (
            <div key={c.id} style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 12, padding: "16px 18px", display: "flex", flexDirection: "column", gap: 12, borderTop: `3px solid ${running ? "#10B981" : "#E2E5EA"}` }}>
              {/* Top row */}
              <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                <div style={{ width: 36, height: 36, borderRadius: 9, flexShrink: 0, background: running ? "#10B98115" : "#F4F5F7", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>
                  {running ? "▣" : "□"}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#1A1D23", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</div>
                  <div style={{ fontSize: 10, color: "#9BA3AF", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.image}</div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, flexShrink: 0 }}>
                  <span style={{ fontSize: 9, padding: "2px 7px", borderRadius: 99, letterSpacing: 0.5, fontWeight: 600, color: st.color, background: st.bg }}>{st.label}</span>
                  {!managed && (
                    <span title="非本应用创建的容器，仅展示" style={{ fontSize: 9, padding: "1px 6px", borderRadius: 99, fontWeight: 600, color: "#9BA3AF", background: "#F4F5F7", border: "1px solid #E2E5EA" }}>外部</span>
                  )}
                </div>
              </div>

              {/* Ports */}
              {c.ports.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                  {c.ports.map((p) => (
                    <span key={p} style={{ fontSize: 10, padding: "2px 8px", borderRadius: 5, background: "#F4F5F7", color: "#6B7280", fontFamily: "monospace", border: "1px solid #E2E5EA" }}>{p}</span>
                  ))}
                </div>
              )}

              {/* Tags from env_vars as chips */}
              {c.env_vars.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {c.env_vars.slice(0, 4).map((e) => (
                    <span key={e} style={{ fontSize: 9, padding: "1px 7px", borderRadius: 99, background: "#4F6EF711", color: "#4F6EF7" }}>{e.split("=")[0]}</span>
                  ))}
                </div>
              )}

              {/* Actions —— 仅本应用创建（managed）的容器可操作；外部容器只读 */}
              {managed ? (
                <div style={{ display: "flex", gap: 8, borderTop: "1px solid #F4F5F7", paddingTop: 10 }}>
                  <button
                    onClick={() => handleToggle(c)}
                    disabled={isAction}
                    style={{ flex: 1, fontSize: 11, padding: "6px 0", borderRadius: 7, cursor: isAction ? "default" : "pointer", fontFamily: "inherit", border: `1px solid ${running ? "#F59E0B44" : "#10B98144"}`, background: running ? "#F59E0B11" : "#10B98111", color: running ? "#F59E0B" : "#10B981", opacity: isAction ? 0.5 : 1 }}
                  >
                    {isAction ? "…" : running ? "⏸ 停止" : "▶ 启动"}
                  </button>
                  {confirming ? (
                    <div style={{ display: "flex", gap: 4 }}>
                      <button onClick={() => handleDelete(c.id)} style={{ fontSize: 11, padding: "6px 10px", borderRadius: 7, cursor: "pointer", fontFamily: "inherit", border: "1px solid #EF444433", background: "#EF444411", color: "#EF4444" }}>
                        确认
                      </button>
                      <button onClick={() => setDeleteId(null)} style={{ fontSize: 11, padding: "6px 10px", borderRadius: 7, cursor: "pointer", fontFamily: "inherit", border: "1px solid #E2E5EA", background: "transparent", color: "#9BA3AF" }}>
                        取消
                      </button>
                    </div>
                  ) : (
                    <button onClick={() => handleDelete(c.id)} style={{ fontSize: 11, padding: "6px 12px", borderRadius: 7, cursor: "pointer", fontFamily: "inherit", border: "1px solid #EF444433", background: "#EF444411", color: "#EF4444" }}>
                      删除
                    </button>
                  )}
                </div>
              ) : (
                <div style={{ borderTop: "1px solid #F4F5F7", paddingTop: 10, fontSize: 10, color: "#9BA3AF", textAlign: "center" }}>
                  外部容器 · 仅展示
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* New Container Modal */}
      {showCreate && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.2)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
          <div style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 14, width: "100%", maxWidth: 480, boxShadow: "0 24px 64px rgba(0,0,0,0.1)" }}>
            <div style={{ display: "flex", alignItems: "center", padding: "16px 24px", borderBottom: "1px solid #E2E5EA" }}>
              <span style={{ flex: 1, fontSize: 14, fontWeight: 700, color: "#1A1D23" }}>新建容器</span>
              <button onClick={() => setShowCreate(false)} style={{ background: "transparent", border: "none", color: "#9BA3AF", cursor: "pointer", fontSize: 14, fontFamily: "inherit" }}>✕</button>
            </div>
            <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 14 }}>
              <FieldBox label="容器名称">
                <input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="e.g. mysql-8"
                  style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "8px 12px", color: "#1A1D23", fontSize: 12, fontFamily: "inherit", outline: "none", width: "100%", boxSizing: "border-box" }} />
              </FieldBox>
              <FieldBox label="镜像">
                <input value={form.image} onChange={(e) => setForm((f) => ({ ...f, image: e.target.value }))} placeholder="e.g. mysql:8.0"
                  style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "8px 12px", color: "#1A1D23", fontSize: 12, fontFamily: "inherit", outline: "none", width: "100%", boxSizing: "border-box" }} />
              </FieldBox>
              <FieldBox label="端口映射（逗号分隔）">
                <input value={form.ports} onChange={(e) => setForm((f) => ({ ...f, ports: e.target.value }))} placeholder="e.g. 3306:3306, 33060:33060"
                  style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "8px 12px", color: "#1A1D23", fontSize: 12, fontFamily: "inherit", outline: "none", width: "100%", boxSizing: "border-box" }} />
              </FieldBox>
              <FieldBox label="环境变量（逗号分隔，KEY=VALUE）">
                <input value={form.env_vars} onChange={(e) => setForm((f) => ({ ...f, env_vars: e.target.value }))} placeholder="e.g. MYSQL_ROOT_PASSWORD=secret"
                  style={{ background: "#FFFFFF", border: "1px solid #E2E5EA", borderRadius: 8, padding: "8px 12px", color: "#1A1D23", fontSize: 12, fontFamily: "inherit", outline: "none", width: "100%", boxSizing: "border-box" }} />
              </FieldBox>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, padding: "14px 24px", borderTop: "1px solid #E2E5EA" }}>
              <button onClick={() => setShowCreate(false)} style={{ fontSize: 12, padding: "7px 16px", borderRadius: 8, background: "transparent", border: "1px solid #E2E5EA", color: "#6B7280", cursor: "pointer", fontFamily: "inherit" }}>取消</button>
              <button onClick={handleCreate} style={{ fontSize: 12, padding: "8px 18px", borderRadius: 8, background: "#4F6EF718", border: "1px solid #4F6EF744", color: "#4F6EF7", cursor: "pointer", fontFamily: "inherit", opacity: form.name && form.image ? 1 : 0.4 }}>
                创建
              </button>
            </div>
          </div>
        </div>
      )}
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
