/**
 * ConfigPage — 运行时配置管理。
 * 每个配置分组以「气泡卡片」呈现，保存按分组提交 PATCH /config。
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "@/shared/lib/api";

// ─── 类型 ─────────────────────────────────────────────────────────────

type FieldType = "text" | "password" | "number" | "toggle" | "ratio" | "readonly";

interface Field {
  key: string;
  label: string;
  type: FieldType;
  hint?: string;
  min?: number;
  max?: number;
  step?: number;
}

interface Group {
  key: string;
  title: string;
  icon: string;
  accent: string;      // 气泡左侧色条颜色
  fields: Field[];
}

// ─── 分组定义 ─────────────────────────────────────────────────────────

const GROUPS: Group[] = [
  {
    key: "api",
    title: "模型接口",
    icon: "◎",
    accent: "#4F6EF7",
    fields: [
      { key: "anthropic_api_key",   label: "Anthropic API Key",  type: "password", hint: "sk-ant-…" },
      { key: "anthropic_auth_token",label: "Auth Token",         type: "password", hint: "Bearer 风格 token" },
      { key: "anthropic_base_url",  label: "API Base URL",       type: "text",     hint: "留空使用官方端点" },
    ],
  },
  {
    key: "models",
    title: "模型配置",
    icon: "◈",
    accent: "#8B5CF6",
    fields: [
      { key: "model_high", label: "高级模型", type: "text", hint: "复杂推理、长上下文" },
      { key: "model_mid",  label: "正常模型", type: "text", hint: "主代理 / 子 agent 默认" },
      { key: "model_low",  label: "低级模型", type: "text", hint: "摘要、标题生成、context 压缩" },
    ],
  },
  {
    key: "features",
    title: "功能开关",
    icon: "◉",
    accent: "#10B981",
    fields: [
      { key: "context_compression_enabled", label: "上下文压缩",   type: "toggle", hint: "达到阈值时用低级模型压缩旧消息" },
      { key: "enable_prompt_cache",         label: "Prompt Cache", type: "toggle", hint: "官方端点支持时开启，降低重复 token 费用" },
    ],
  },
  {
    key: "compression",
    title: "上下文压缩",
    icon: "◷",
    accent: "#F59E0B",
    fields: [
      { key: "model_context_window",        label: "上下文窗口（tokens）",   type: "number", min: 8000,  max: 2000000, hint: "模型最大上下文大小" },
      { key: "context_compression_ratio",   label: "压缩触发比例",          type: "ratio",  min: 0.5,   max: 0.95, step: 0.05, hint: "默认 0.80（80%）" },
      { key: "context_compression_threshold", label: "当前触发阈值（tokens，自动计算）", type: "readonly" },
      { key: "context_summary_threshold",   label: "子 Agent context 压缩阈值（字符）", type: "number", min: 1000, max: 100000 },
      { key: "context_summary_target_chars",label: "摘要目标长度（字符）",   type: "number", min: 200,  max: 10000 },
    ],
  },
  {
    key: "budget",
    title: "Token 预算",
    icon: "◆",
    accent: "#EF4444",
    fields: [
      { key: "session_token_limit", label: "会话上限（tokens）", type: "number", min: 10000,    max: 10000000 },
      { key: "daily_token_limit",   label: "每日上限（tokens）", type: "number", min: 100000,   max: 100000000 },
    ],
  },
  {
    key: "subagent",
    title: "子 Agent",
    icon: "▣",
    accent: "#06B6D4",
    fields: [
      { key: "sub_agent_max_depth",             label: "最大调用深度",         type: "number", min: 1, max: 5 },
      { key: "sub_agent_max_tool_iterations",   label: "工具循环上限",         type: "number", min: 1, max: 50 },
      { key: "sub_agent_max_recovery_attempts", label: "最大恢复次数",         type: "number", min: 0, max: 10 },
    ],
  },
  {
    key: "tools",
    title: "工具配置",
    icon: "◧",
    accent: "#6B7280",
    fields: [
      { key: "max_tool_calls_per_turn",   label: "单轮最大工具数",     type: "number", min: 1,    max: 50 },
      { key: "max_tool_output_chars",    label: "工具输出字符上限",   type: "number", min: 1000, max: 200000 },
      { key: "tool_concurrency",         label: "并发工具执行数",     type: "number", min: 1,    max: 20 },
      { key: "tool_failure_max_retries", label: "单工具失败上限",     type: "number", min: 1,    max: 10 },
      { key: "max_tool_iterations",      label: "步数软上限",         type: "number", min: 1,    max: 200 },
    ],
  },
];

// ─── 主组件 ───────────────────────────────────────────────────────────

export function ConfigPage() {
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [drafts, setDrafts] = useState<Record<string, Record<string, unknown>>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const cfg = await api.getConfig();
      setValues(cfg);
      // 初始化各分组草稿（readonly 字段不进 draft，直接从 values 读）
      setDrafts((prev) => {
        const init: Record<string, Record<string, unknown>> = {};
        for (const g of GROUPS) {
          init[g.key] = { ...(prev[g.key] ?? {}) };
          for (const f of g.fields) {
            if (f.type === "readonly") continue;
            // 已有草稿且不是初次加载时保留用户编辑中的值
            if (silent && prev[g.key]?.[f.key] !== undefined) continue;
            // 密码字段：draft 始终初始化为空串，避免用户在掩码值末尾追加导致 • 检测误判
            init[g.key][f.key] = f.type === "password" ? "" : (cfg[f.key] ?? "");
          }
        }
        return init;
      });
    } catch (e) {
      setError(`加载失败：${e}`);
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  function setField(groupKey: string, fieldKey: string, val: unknown) {
    setDrafts((d) => ({
      ...d,
      [groupKey]: { ...d[groupKey], [fieldKey]: val },
    }));
  }

  async function saveGroup(group: Group) {
    setSaving((s) => ({ ...s, [group.key]: true }));
    setError(null);
    try {
      const updates: Record<string, unknown> = {};
      for (const f of group.fields) {
        if (f.type === "readonly") continue;
        const raw = drafts[group.key]?.[f.key];
        // 密码字段：draft 为空串时跳过（用户未输入新值，不覆盖现有配置）
        if (f.type === "password" && (raw === "" || raw === null || raw === undefined)) continue;
        if (raw !== "" && raw !== null && raw !== undefined) {
          updates[f.key] = f.type === "number" ? Number(raw)
            : f.type === "ratio"  ? Number(raw)
            : f.type === "toggle" ? Boolean(raw)
            : raw;
        }
      }
      await api.patchConfig(updates);
      setValues((v) => ({ ...v, ...updates }));
      setSaved((s) => ({ ...s, [group.key]: true }));
      setTimeout(() => setSaved((s) => ({ ...s, [group.key]: false })), 2000);
      // 压缩分组保存后刷新计算属性（context_compression_threshold）
      if (group.key === "compression") await load(true);
    } catch (e) {
      setError(`保存失败：${e}`);
    } finally {
      setSaving((s) => ({ ...s, [group.key]: false }));
    }
  }

  if (loading) {
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "#9BA3AF", fontSize: 13 }}>
        加载配置中…
      </div>
    );
  }

  return (
    <div style={{ flex: 1, overflowY: "auto", background: "#F4F5F7", padding: "32px 40px" }}>
      {/* 页头 */}
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: "#1A1D23", letterSpacing: -0.3 }}>配置</h1>
        <p style={{ margin: "4px 0 0", fontSize: 12, color: "#9BA3AF" }}>
          修改保存后立即生效，无需重启。敏感字段展示为脱敏值，输入新值可覆盖。
        </p>
      </div>

      {error && (
        <div style={{ marginBottom: 16, padding: "10px 16px", background: "#FEF2F2", border: "1px solid #FECACA", borderRadius: 10, fontSize: 12, color: "#DC2626" }}>
          {error}
        </div>
      )}

      {/* 气泡网格 */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(420px, 1fr))", gap: 20 }}>
        {GROUPS.map((group) => (
          <Bubble
            key={group.key}
            group={group}
            draft={drafts[group.key] ?? {}}
            values={values}
            saving={!!saving[group.key]}
            saved={!!saved[group.key]}
            onChange={(fk, v) => setField(group.key, fk, v)}
            onSave={() => saveGroup(group)}
          />
        ))}
      </div>
    </div>
  );
}

// ─── 气泡卡片 ─────────────────────────────────────────────────────────

interface BubbleProps {
  group: Group;
  draft: Record<string, unknown>;
  values: Record<string, unknown>;
  saving: boolean;
  saved: boolean;
  onChange: (fieldKey: string, value: unknown) => void;
  onSave: () => void;
}

function Bubble({ group, draft, values, saving, saved, onChange, onSave }: BubbleProps) {
  return (
    <div style={{
      background: "#FFFFFF",
      borderRadius: 20,
      boxShadow: "0 2px 16px rgba(0,0,0,0.06)",
      overflow: "hidden",
      display: "flex",
      flexDirection: "column",
    }}>
      {/* 气泡头 */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "14px 20px",
        borderBottom: `3px solid ${group.accent}18`,
        background: `${group.accent}08`,
      }}>
        <span style={{ fontSize: 16, color: group.accent }}>{group.icon}</span>
        <span style={{ fontSize: 13, fontWeight: 700, color: "#1A1D23", letterSpacing: -0.2 }}>{group.title}</span>
        <div style={{ flex: 1 }} />
        <div style={{
          width: 10, height: 10, borderRadius: "50%",
          background: group.accent, opacity: 0.4,
        }} />
      </div>

      {/* 字段列表 */}
      <div style={{ padding: "12px 20px 8px", display: "flex", flexDirection: "column", gap: 12, flex: 1 }}>
        {group.fields.map((field) => (
          <FieldRow
            key={field.key}
            field={field}
            value={field.type === "readonly" ? values[field.key] : draft[field.key]}
            serverValue={field.type === "password" ? values[field.key] : undefined}
            accent={group.accent}
            onChange={(v) => onChange(field.key, v)}
          />
        ))}
      </div>

      {/* 保存按钮（纯只读分组不显示） */}
      {group.fields.some((f) => f.type !== "readonly") && (
        <div style={{ padding: "10px 20px 16px", display: "flex", justifyContent: "flex-end" }}>
          <button
            onClick={onSave}
            disabled={saving}
            style={{
              fontSize: 11, fontWeight: 600, padding: "7px 18px",
              borderRadius: 10, border: "none", cursor: saving ? "wait" : "pointer",
              background: saved ? "#10B98118" : `${group.accent}18`,
              color: saved ? "#10B981" : group.accent,
              transition: "all 0.2s", fontFamily: "inherit",
            }}
          >
            {saving ? "保存中…" : saved ? "✓ 已保存" : "应用"}
          </button>
        </div>
      )}
    </div>
  );
}

// ─── 字段行 ───────────────────────────────────────────────────────────

interface FieldRowProps {
  field: Field;
  value: unknown;
  serverValue?: unknown;
  accent: string;
  onChange: (v: unknown) => void;
}

function FieldRow({ field, value, serverValue, accent, onChange }: FieldRowProps) {
  const str = value === null || value === undefined ? "" : String(value);
  // 密码字段：draft 始终为空串，用 serverValue（掩码值）做 placeholder
  const pwPlaceholder = field.type === "password"
    ? (serverValue ? String(serverValue) : (field.hint ?? "未设置"))
    : undefined;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: "#374151", flex: 1 }}>{field.label}</span>
        {field.hint && (
          <span style={{ fontSize: 10, color: "#C0C5CE" }}>{field.hint}</span>
        )}
      </div>

      {field.type === "readonly" ? (
        <div style={{
          fontSize: 12, padding: "7px 12px",
          background: "#F9FAFB", border: "1px dashed #E2E5EA",
          borderRadius: 8, color: "#6B7280",
          fontFamily: "monospace", letterSpacing: 0.3,
        }}>
          {str || "—"}
        </div>
      ) : field.type === "toggle" ? (
        <Toggle value={!!value} accent={accent} onChange={onChange} />
      ) : field.type === "ratio" ? (
        <RatioSlider value={Number(str) || 0.8} field={field} accent={accent} onChange={onChange} />
      ) : (
        <input
          type={field.type === "password" ? "password" : field.type === "number" ? "number" : "text"}
          value={str}
          min={field.min}
          max={field.max}
          placeholder={pwPlaceholder}
          autoComplete={field.type === "password" ? "off" : undefined}
          onChange={(e) => onChange(e.target.value)}
          style={{
            fontSize: 12, padding: "7px 12px",
            background: "#F4F5F7", border: "1px solid #E2E5EA",
            borderRadius: 8, outline: "none", color: "#1A1D23",
            fontFamily: field.type === "password" ? "monospace" : "inherit",
            width: "100%", boxSizing: "border-box",
            transition: "border-color 0.15s",
          }}
          onFocus={(e) => { e.target.style.borderColor = accent; }}
          onBlur={(e) => { e.target.style.borderColor = "#E2E5EA"; }}
        />
      )}
    </div>
  );
}

// ─── Toggle ───────────────────────────────────────────────────────────

function Toggle({ value, accent, onChange }: { value: boolean; accent: string; onChange: (v: unknown) => void }) {
  return (
    <button
      role="switch"
      aria-checked={value}
      onClick={() => onChange(!value)}
      style={{
        alignSelf: "flex-start",
        width: 44, height: 24, borderRadius: 12,
        background: value ? accent : "#E2E5EA",
        border: "none", cursor: "pointer", position: "relative",
        transition: "background 0.2s", padding: 0,
        flexShrink: 0,
      }}
    >
      <span style={{
        position: "absolute", top: 3,
        left: value ? 22 : 3,
        width: 18, height: 18, borderRadius: "50%",
        background: "#FFFFFF",
        boxShadow: "0 1px 4px rgba(0,0,0,0.2)",
        transition: "left 0.2s",
        display: "block",
      }} />
    </button>
  );
}

// ─── RatioSlider ──────────────────────────────────────────────────────

function RatioSlider({ value, field, accent, onChange }: { value: number; field: Field; accent: string; onChange: (v: unknown) => void }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <input
        type="range"
        min={field.min ?? 0}
        max={field.max ?? 1}
        step={field.step ?? 0.05}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ flex: 1, accentColor: accent }}
      />
      <span style={{ fontSize: 12, fontWeight: 600, color: accent, minWidth: 36, textAlign: "right" }}>
        {Math.round(value * 100)}%
      </span>
    </div>
  );
}
