/**
 * Right-side 300px panel — 三标签：任务 / 看板 / 环境。
 *   任务  turn 分组的 phase 树（主/子代理/技能，带状态 + 可展开日志）
 *   看板  本平台 artifact 总览（api.listArtifacts；按 kind 过滤；secret 类不回明文）
 *   环境  执行环境选择器（物理机 + managed 容器）
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Artifact, type Container } from "@/shared/lib/api";
import { useChat, type Phase, type TurnGroup } from "@/store/chat";

const MAIN = "#4F6EF7";

const TASK_STATUS: Record<string, { label: string; color: string }> = {
  pending: { label: "等待中", color: "#6B7280" },
  running: { label: "运行中", color: "#F59E0B" },
  ok:      { label: "已完成", color: "#10B981" },
  done:    { label: "已完成", color: "#10B981" },
  failed:  { label: "失败",   color: "#EF4444" },
  pass:    { label: "已汇总", color: "#4F6EF7" },
  revise:  { label: "修订中", color: "#F59E0B" },
};

const CONTAINER_STATUS: Record<string, { label: string; color: string; bg: string }> = {
  running: { label: "运行中", color: "#10B981", bg: "#10B98115" },
  stopped: { label: "已停止", color: "#9BA3AF", bg: "#9BA3AF15" },
  created: { label: "已创建", color: "#F59E0B", bg: "#F59E0B15" },
};

// finding 严重级 → 色（左侧圆点）
const SEVERITY: Record<string, string> = {
  critical: "#DC2626",
  high:     "#EF4444",
  medium:   "#F59E0B",
  low:      "#10B981",
  info:     "#9BA3AF",
};

// 敏感级 → pill 样式
const SENSITIVITY: Record<string, { label: string; color: string; bg: string; lock?: boolean }> = {
  secret:   { label: "secret",   color: "#B45309", bg: "#FEF3C7", lock: true },
  internal: { label: "internal", color: "#6B7280", bg: "#F1F1F3" },
  public:   { label: "public",   color: "#0F766E", bg: "#CCFBF1" },
};

const KIND_LABEL: Record<string, string> = {
  finding:     "finding",
  scan_result: "scan",
  recon:       "recon",
  report:      "report",
  note:        "note",
};

// 按 phase.id 前缀解析 agent 身份 → 显示名 + 类别色。
function agentIdentity(id: string): { name: string; color: string } {
  if (id === "agent") return { name: "主代理", color: "#4F6EF7" };
  if (id.startsWith("sub_agent:")) return { name: `子代理 · ${id.slice(10)}`, color: "#7C3AED" };
  if (id.startsWith("skill:")) return { name: `技能 · ${id.slice(6)}`, color: "#0D9488" };
  if (id.startsWith("agent:")) return { name: `主代理 · ${id.slice(6)}`, color: "#4F6EF7" };
  return { name: id.split(":")[0], color: "#6B7280" };
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <span style={{
      fontSize: 9,
      fontWeight: 700,
      letterSpacing: 1.5,
      color: "#B0B7C3",
      textTransform: "uppercase" as const,
    }}>
      {children}
    </span>
  );
}

function fmtClock(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
}

type Tab = "tasks" | "board" | "env";

export function TasksPanel() {
  const turn            = useChat((s) => s.turn);
  const sessionId       = useChat((s) => s.currentSessionId);
  const groupsBySession = useChat((s) => s.taskGroups);
  const executionEnv    = useChat((s) => s.executionEnv);
  const setExecutionEnv = useChat((s) => s.setExecutionEnv);
  const [containers, setContainers] = useState<Container[]>([]);
  const [tab, setTab] = useState<Tab>("tasks");

  useEffect(() => {
    api.listContainers()
      .then((cs) => {
        const managed = cs.filter((c) => c.managed);
        setContainers(managed);
        const env = useChat.getState().executionEnv;
        if (env.startsWith("container:")) {
          const id = env.slice("container:".length);
          if (!managed.some((c) => c.id === id && c.status === "running")) {
            useChat.getState().setExecutionEnv("local");
          }
        }
      })
      .catch(() => setContainers([]));
  }, []);

  const history = (sessionId && groupsBySession[sessionId]) || [];
  const liveGroup: TurnGroup | null =
    turn.inFlight || turn.phases.length > 0
      ? {
          id: "__live__",
          userText: turn.userText,
          ts: "",
          phases: turn.phases,
          taskLogs: turn.taskLogs,
          taskLabels: turn.taskLabels,
        }
      : null;
  const display: { group: TurnGroup; live: boolean }[] = [
    ...(liveGroup ? [{ group: liveGroup, live: true }] : []),
    ...history.slice().reverse().map((g) => ({ group: g, live: false })),
  ];

  const liveParents = (liveGroup?.phases ?? []).filter((p) => !p.parent_id);
  const counts = {
    running: liveParents.filter((p) => p.status === "running").length,
    ok:      liveParents.filter((p) => p.status === "ok" || p.status === "pass").length,
    failed:  liveParents.filter((p) => p.status === "failed").length,
  };

  return (
    <aside style={{
      width: 300,
      background: "#FFFFFF",
      borderLeft: "1px solid #E2E5EA",
      display: "flex",
      flexDirection: "column",
      flexShrink: 0,
      overflow: "hidden",
    }}>
      {/* ── 三标签 ─────────────────────────────────────────── */}
      <div style={{ display: "flex", borderBottom: "1px solid #E2E5EA", flexShrink: 0 }}>
        <TabButton label="任务" active={tab === "tasks"} onClick={() => setTab("tasks")}>
          {counts.running > 0 && (
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#F59E0B" }} />
          )}
        </TabButton>
        <TabButton label="看板" active={tab === "board"} onClick={() => setTab("board")} />
        <TabButton label="环境" active={tab === "env"} onClick={() => setTab("env")} />
      </div>

      {tab === "tasks" && <TasksBody display={display} counts={counts} />}
      {tab === "board" && <BoardBody />}
      {tab === "env" && (
        <EnvBody
          containers={containers}
          executionEnv={executionEnv}
          setExecutionEnv={setExecutionEnv}
        />
      )}
    </aside>
  );
}

function TabButton({
  label, active, onClick, children,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  children?: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        flex: 1,
        padding: "9px 0",
        fontSize: 11,
        fontWeight: 500,
        background: "transparent",
        border: "none",
        borderBottom: `1.5px solid ${active ? MAIN : "transparent"}`,
        color: active ? MAIN : "#9BA3AF",
        cursor: "pointer",
        fontFamily: "inherit",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 5,
      }}
    >
      {label}
      {children}
    </button>
  );
}

// ── 任务 tab ────────────────────────────────────────────────
function TasksBody({
  display, counts,
}: {
  display: { group: TurnGroup; live: boolean }[];
  counts: { running: number; ok: number; failed: number };
}) {
  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "10px 14px 8px", display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <SectionLabel>Tasks</SectionLabel>
        <span style={{ flex: 1 }} />
        {counts.running > 0 && <span style={{ fontSize: 11, color: "#F59E0B", fontWeight: 500 }}>{counts.running} 运行</span>}
        {counts.ok > 0 && <span style={{ fontSize: 11, color: "#10B981", fontWeight: 500 }}>{counts.ok} 完成</span>}
        {counts.failed > 0 && <span style={{ fontSize: 11, color: "#EF4444", fontWeight: 500 }}>{counts.failed} 失败</span>}
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column" }}>
        {display.length === 0 && (
          <div style={{ fontSize: 11, color: "#C0C5CE", textAlign: "center", marginTop: 24 }}>
            暂无任务
          </div>
        )}
        {display.map(({ group, live }) => (
          <TurnGroupView key={group.id} group={group} live={live} />
        ))}
      </div>
    </div>
  );
}

// ── 看板 tab ────────────────────────────────────────────────
function BoardBody() {
  const [items, setItems] = useState<Artifact[] | null>(null);
  const [err, setErr] = useState(false);
  const [kind, setKind] = useState<string | null>(null);

  const load = useCallback(() => {
    setErr(false);
    api.listArtifacts()
      .then((rows) => setItems(rows))
      .catch(() => { setItems([]); setErr(true); });
  }, []);

  useEffect(() => { load(); }, [load]);

  const kinds = useMemo(() => {
    const seen: string[] = [];
    (items ?? []).forEach((a) => { if (!seen.includes(a.kind)) seen.push(a.kind); });
    return seen;
  }, [items]);

  const shown = (items ?? []).filter((a) => !kind || a.kind === kind);

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "10px 14px 8px", display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
        <SectionLabel>看板</SectionLabel>
        {items && <span style={{ fontSize: 10, color: "#C0C5CE" }}>{items.length}</span>}
        <span style={{ flex: 1 }} />
        <button
          onClick={load}
          title="刷新"
          style={{ background: "none", border: "none", cursor: "pointer", fontSize: 12, color: "#9BA3AF", padding: 0, fontFamily: "inherit" }}
        >
          ↻
        </button>
      </div>

      {kinds.length > 0 && (
        <div style={{ display: "flex", gap: 6, padding: "0 12px 8px", flexWrap: "wrap", flexShrink: 0 }}>
          <KindChip label="全部" active={kind === null} onClick={() => setKind(null)} />
          {kinds.map((k) => (
            <KindChip key={k} label={KIND_LABEL[k] ?? k} active={kind === k} onClick={() => setKind(k)} />
          ))}
        </div>
      )}

      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "0 12px 12px", display: "flex", flexDirection: "column", gap: 8 }}>
        {items === null && (
          <div style={{ fontSize: 11, color: "#C0C5CE", textAlign: "center", marginTop: 24 }}>加载中…</div>
        )}
        {items !== null && shown.length === 0 && (
          <div style={{ fontSize: 11, color: "#C0C5CE", textAlign: "center", marginTop: 24 }}>
            {err ? "加载失败，点 ↻ 重试" : "看板暂无产出"}
          </div>
        )}
        {shown.map((a) => <ArtifactCard key={a.id} a={a} />)}
      </div>
    </div>
  );
}

function KindChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        fontSize: 11,
        padding: "2px 9px",
        borderRadius: 20,
        border: `1px solid ${active ? "#4F6EF766" : "#E2E5EA"}`,
        background: active ? "#4F6EF710" : "transparent",
        color: active ? MAIN : "#6B7280",
        cursor: "pointer",
        fontFamily: "inherit",
      }}
    >
      {label}
    </button>
  );
}

function ArtifactCard({ a }: { a: Artifact }) {
  const isFinding = a.kind === "finding";
  const isSecret = a.sensitivity === "secret";
  const sens = SENSITIVITY[a.sensitivity] ?? SENSITIVITY.internal;
  const sevColor = SEVERITY[a.severity ?? "info"] ?? "#9BA3AF";
  const time = fmtClock(a.created_at);

  return (
    <div style={{
      border: `1px solid ${isSecret ? "#FCD97A" : "#E2E5EA"}`,
      borderRadius: 12,
      background: "#FFFFFF",
      padding: "9px 11px",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
        {isSecret ? (
          <span style={{ fontSize: 12, color: "#B45309", flexShrink: 0 }}>🔒</span>
        ) : isFinding ? (
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: sevColor, flexShrink: 0 }} />
        ) : (
          <span style={{ width: 7, height: 7, borderRadius: 2, background: "#C0C5CE", flexShrink: 0 }} />
        )}
        <span style={{ fontSize: 12, fontWeight: 500, color: "#1A1D23", flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {a.title}
        </span>
        {isFinding && a.severity && (
          <span style={{ fontSize: 10, fontFamily: "monospace", padding: "1px 6px", borderRadius: 20, color: sevColor, background: `${sevColor}18` }}>
            {a.severity}
          </span>
        )}
        <span style={{ fontSize: 10, padding: "1px 7px", borderRadius: 20, color: sens.color, background: sens.bg }}>
          {sens.label}
        </span>
      </div>

      <div style={{
        fontSize: 11,
        color: isSecret ? "#9BA3AF" : "#6B7280",
        fontStyle: isSecret ? "italic" : "normal",
        lineHeight: 1.5,
        display: "-webkit-box",
        WebkitLineClamp: 2,
        WebkitBoxOrient: "vertical" as const,
        overflow: "hidden",
      }}>
        {isSecret ? "正文已保险箱托管，不回明文" : (a.content || "（无正文）")}
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 5, fontSize: 10, color: "#C0C5CE", alignItems: "center" }}>
        <span style={{ fontFamily: "monospace" }}>{KIND_LABEL[a.kind] ?? a.kind}</span>
        {a.producer && <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 90 }}>{a.producer}</span>}
        {isSecret && a.vault_ref && <span style={{ fontFamily: "monospace", color: "#B45309" }}>{a.vault_ref}</span>}
        {time && <span style={{ marginLeft: "auto" }}>{time}</span>}
      </div>
    </div>
  );
}

// ── 环境 tab ────────────────────────────────────────────────
function EnvBody({
  containers, executionEnv, setExecutionEnv,
}: {
  containers: Container[];
  executionEnv: string;
  setExecutionEnv: (v: string) => void;
}) {
  function toggleEnv(c: Container) {
    if (c.status !== "running") return;
    const next = executionEnv === `container:${c.id}` ? "local" : `container:${c.id}`;
    setExecutionEnv(next);
  }

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "10px 16px 6px", display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
        <SectionLabel>环境</SectionLabel>
        <span style={{ fontSize: 9, color: "#C0C5CE" }}>
          {executionEnv === "local" ? "物理机" : containers.find((c) => `container:${c.id}` === executionEnv)?.name ?? executionEnv}
        </span>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "0 12px 12px", display: "flex", flexDirection: "column", gap: 6 }}>
        <div
          onClick={() => setExecutionEnv("local")}
          style={{
            background: executionEnv === "local" ? "#4F6EF708" : "#F9FAFB",
            border: `1px solid ${executionEnv === "local" ? "#4F6EF766" : "#E2E5EA"}`,
            borderRadius: 8,
            padding: "7px 10px",
            display: "flex",
            alignItems: "center",
            gap: 8,
            cursor: "pointer",
            transition: "all 0.12s",
          }}
        >
          <ActiveDot active={executionEnv === "local"} />
          <span style={{ fontSize: 11, fontWeight: 600, color: executionEnv === "local" ? "#4F6EF7" : "#374151" }}>
            物理机
          </span>
          <span style={{ marginLeft: "auto", fontSize: 9, color: "#C0C5CE" }}>local</span>
        </div>

        {containers.length === 0 && (
          <div style={{ fontSize: 10, color: "#C0C5CE", textAlign: "center", paddingTop: 12 }}>
            无可用容器
          </div>
        )}

        {containers.map((c) => {
          const st  = CONTAINER_STATUS[c.status] ?? CONTAINER_STATUS.stopped;
          const sel = executionEnv === `container:${c.id}`;
          const can = c.status === "running";
          return (
            <div
              key={c.id}
              onClick={() => toggleEnv(c)}
              style={{
                background: sel ? "#4F6EF708" : "#F9FAFB",
                border: `1px solid ${sel ? "#4F6EF766" : "#E2E5EA"}`,
                borderRadius: 8,
                padding: "7px 10px",
                display: "flex",
                flexDirection: "column",
                gap: 4,
                cursor: can ? "pointer" : "default",
                opacity: can ? 1 : 0.5,
                transition: "all 0.12s",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <ActiveDot active={sel} />
                <span style={{ fontSize: 11, fontWeight: 600, color: sel ? "#4F6EF7" : "#374151", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {c.name}
                </span>
                <span style={{ fontSize: 9, padding: "1px 6px", borderRadius: 99, fontWeight: 600, color: st.color, background: st.bg }}>
                  {st.label}
                </span>
              </div>
              <div style={{ display: "flex", gap: 6, marginLeft: 18, alignItems: "center" }}>
                <span style={{ fontSize: 9, color: "#9BA3AF" }}>{c.image}</span>
                {c.ports.slice(0, 2).map((p) => (
                  <span key={p} style={{ fontSize: 9, padding: "0 5px", borderRadius: 3, background: "#F4F5F7", color: "#6B7280", fontFamily: "monospace" }}>
                    {p}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ActiveDot({ active }: { active: boolean }) {
  return (
    <div style={{
      width: 14,
      height: 14,
      borderRadius: 3,
      flexShrink: 0,
      border: `1.5px solid ${active ? "#4F6EF7" : "#D1D5DB"}`,
      background: active ? "#4F6EF7" : "transparent",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
    }}>
      {active && <span style={{ color: "#fff", fontSize: 9, lineHeight: 1 }}>✓</span>}
    </div>
  );
}

// ── 一个轮次分组：可折叠，标题=该轮用户问题，body=紧凑 phase 行树 ──────────
function TurnGroupView({ group, live }: { group: TurnGroup; live: boolean }) {
  const [open, setOpen] = useState(live);
  const roots = group.phases.filter((p) => !p.parent_id);
  const title = group.userText.trim() || (live ? "当前任务" : "历史任务");

  return (
    <div style={{ borderBottom: "1px solid #F0F1F3" }}>
      <div
        onClick={() => setOpen((v) => !v)}
        style={{
          padding: "7px 12px",
          display: "flex",
          alignItems: "center",
          gap: 7,
          cursor: "pointer",
          background: live ? "#4F6EF70A" : "#F8F9FB",
        }}
      >
        <span style={{ fontSize: 10, color: "#9BA3AF", width: 10, flexShrink: 0 }}>{open ? "▾" : "▸"}</span>
        {live && <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#F59E0B", flexShrink: 0, display: "block" }} />}
        <span style={{ flex: 1, fontSize: 11, fontWeight: 500, color: live ? "#374151" : "#6B7280", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {title}
        </span>
        <span style={{ fontSize: 9, color: "#9BA3AF", flexShrink: 0 }}>{roots.length} 项</span>
      </div>
      {open && (
        <div style={{ padding: "2px 0 6px" }}>
          {roots.length === 0 && (
            <span style={{ fontSize: 10, color: "#C0C5CE", padding: "2px 14px" }}>
              {live ? "准备中…" : "无任务记录"}
            </span>
          )}
          {roots.map((p) => (
            <PhaseRow key={p.id} phase={p} phases={group.phases} taskLogs={group.taskLogs} depth={0} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── 紧凑任务行：一行展示身份+状态；有日志时点击展开；子代理缩进递归 ──────────
function PhaseRow({
  phase, phases, taskLogs, depth,
}: {
  phase: Phase;
  phases: Phase[];
  taskLogs: Record<string, string[]>;
  depth: number;
}) {
  const [open, setOpen] = useState(false);
  const ident   = agentIdentity(phase.id);
  const st      = TASK_STATUS[phase.status] ?? TASK_STATUS.pending;
  const logs    = taskLogs[phase.id] ?? [];
  const kids    = phases.filter((p) => p.parent_id === phase.id);
  const hasLogs = logs.length > 0;
  const isMain  = depth === 0;
  const indent  = 14 + depth * 16;

  return (
    <>
      <div
        onClick={hasLogs ? () => setOpen((v) => !v) : undefined}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: `5px 12px 5px ${indent}px`,
          cursor: hasLogs ? "pointer" : "default",
        }}
      >
        <span style={{ width: 7, height: 7, borderRadius: 2, background: ident.color, flexShrink: 0 }} />
        <span style={{
          fontSize: isMain ? 11.5 : 11,
          fontWeight: isMain ? 500 : 400,
          color: isMain ? "#1A1D23" : "#374151",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}>
          {ident.name}
        </span>
        <span style={{ flex: 1, minWidth: 8 }} />
        <span style={{ fontSize: 10, color: st.color, flexShrink: 0 }}>{st.label}</span>
        {hasLogs && (
          <span style={{ fontSize: 10, color: "#C0C5CE", width: 9, flexShrink: 0 }}>{open ? "▾" : "▸"}</span>
        )}
      </div>

      {open && hasLogs && (
        <div style={{
          margin: `0 12px 6px ${indent + 15}px`,
          background: "#F4F5F7",
          borderRadius: 6,
          padding: "6px 8px",
          fontFamily: "'JetBrains Mono',monospace",
          fontSize: 10,
          lineHeight: 1.55,
          color: "#8A929E",
          whiteSpace: "pre-wrap",
          maxHeight: 140,
          overflow: "auto",
        }}>
          {phase.detail && (
            <div style={{ color: "#9BA3AF", marginBottom: 4 }}>{phase.detail}</div>
          )}
          {logs.slice(-12).join("\n")}
        </div>
      )}

      {kids.map((k) => (
        <PhaseRow key={k.id} phase={k} phases={phases} taskLogs={taskLogs} depth={depth + 1} />
      ))}
    </>
  );
}
