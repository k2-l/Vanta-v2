import { useState, type ReactNode } from "react";
import {
  Bell,
  Info,
  Keyboard,
  Palette,
  Plug,
  RefreshCw,
  Stethoscope,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/Button";
import { ModuleLayout, ContextRail, RailItem, ContentHeader } from "@/components/desktop";
import { ConnectionManager } from "@/features/connection/ConnectionManager";
import { useUi, type ThemePref } from "@/stores/ui";
import { useConnection } from "@/stores/connection";
import { useLogout } from "@/features/connection/useActivate";
import { ipc, isTauri } from "@/ipc/client";
import { toClientError } from "@/contracts/errors";

type SectionId =
  | "connection"
  | "appearance"
  | "notifications"
  | "shortcuts"
  | "update"
  | "diagnostics"
  | "about";

const SECTIONS: { id: SectionId; label: string; icon: LucideIcon }[] = [
  { id: "connection", label: "连接", icon: Plug },
  { id: "appearance", label: "外观", icon: Palette },
  { id: "notifications", label: "通知", icon: Bell },
  { id: "shortcuts", label: "快捷键", icon: Keyboard },
  { id: "update", label: "更新", icon: RefreshCw },
  { id: "diagnostics", label: "诊断与日志", icon: Stethoscope },
  { id: "about", label: "关于", icon: Info },
];

export function SettingsPage() {
  const active = (useUi((s) => s.modules.settings.filter) ?? "connection") as SectionId;
  const setFilter = useUi((s) => s.setFilter);

  const rail = (
    <ContextRail title="设置">
      {SECTIONS.map((s) => (
        <RailItem
          key={s.id}
          label={s.label}
          icon={<s.icon size={15} />}
          selected={active === s.id}
          onClick={() => setFilter("settings", s.id)}
        />
      ))}
    </ContextRail>
  );

  const meta = SECTIONS.find((s) => s.id === active)!;

  return (
    <ModuleLayout module="settings" rail={rail}>
      <ContentHeader
        title={meta.label}
        subtitle={isTauri() ? undefined : "浏览器 mock 模式 · 连接与凭据为内存假数据"}
      />
      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-2xl">
          {active === "connection" && <ConnectionSection />}
          {active === "appearance" && <AppearanceSection />}
          {active === "notifications" && <NotificationsSection />}
          {active === "shortcuts" && <ShortcutsSection />}
          {active === "update" && <UpdateSection />}
          {active === "diagnostics" && <DiagnosticsSection />}
          {active === "about" && <AboutSection />}
        </div>
      </div>
    </ModuleLayout>
  );
}

function Card({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section
      className="mb-4 rounded-[var(--radius-lg)] border p-4"
      style={{ background: "var(--surface-overlay)", borderColor: "var(--border)" }}
    >
      <h2 className="text-[13px] font-semibold" style={{ color: "var(--fg)" }}>
        {title}
      </h2>
      {hint && (
        <p className="mt-1 text-[12px]" style={{ color: "var(--fg-muted)" }}>
          {hint}
        </p>
      )}
      <div className="mt-3">{children}</div>
    </section>
  );
}

function ConnectionSection() {
  return (
    <>
      <ConnectionManager />
      <p
        className="mt-4 rounded-[var(--radius)] border px-3 py-2 text-[11px] leading-relaxed"
        style={{ borderColor: "var(--border)", color: "var(--fg-muted)", background: "var(--surface-inset)" }}
      >
        登录令牌由本机 Rust Core 保管。开发联调支持本机和远程 HTTP，上线时使用 HTTPS。
      </p>
    </>
  );
}

function AppearanceSection() {
  const theme = useUi((s) => s.theme);
  const setTheme = useUi((s) => s.setTheme);
  const OPTIONS: { key: ThemePref; label: string; hint: string }[] = [
    { key: "dark", label: "深色", hint: "默认" },
    { key: "light", label: "浅色", hint: "" },
    { key: "system", label: "跟随系统", hint: "" },
  ];
  return (
    <Card title="主题" hint="深色为默认；浅色完整支持；也可跟随系统。">
      <div className="grid grid-cols-3 gap-2">
        {OPTIONS.map((o) => {
          const on = theme === o.key;
          return (
            <button
              key={o.key}
              onClick={() => setTheme(o.key)}
              aria-pressed={on}
              className="flex flex-col items-start gap-1 rounded-[var(--radius)] border px-3 py-2.5 text-left transition-colors"
              style={{
                borderColor: on ? "var(--accent)" : "var(--border)",
                background: on ? "var(--accent-tint)" : "var(--surface-inset)",
              }}
            >
              <span className="text-[13px] font-medium" style={{ color: "var(--fg)" }}>
                {o.label}
              </span>
              {o.hint && (
                <span className="text-[10px]" style={{ color: "var(--fg-subtle)" }}>
                  {o.hint}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </Card>
  );
}

function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <label className="flex items-center justify-between gap-3 py-2">
      <span className="min-w-0">
        <span className="block text-[13px]" style={{ color: "var(--fg)" }}>
          {label}
        </span>
        {hint && (
          <span className="block text-[11px]" style={{ color: "var(--fg-subtle)" }}>
            {hint}
          </span>
        )}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className="relative h-5 w-9 shrink-0 rounded-full transition-colors"
        style={{ background: checked ? "var(--accent)" : "var(--surface-inset)", border: "1px solid var(--border)" }}
      >
        <span
          className="absolute top-1/2 h-3.5 w-3.5 -translate-y-1/2 rounded-full transition-all"
          style={{ left: checked ? 18 : 2, background: "#fff" }}
        />
      </button>
    </label>
  );
}

function NotificationsSection() {
  const [desktop, setDesktop] = useState(true);
  const [sound, setSound] = useState(false);
  const [approvals, setApprovals] = useState(true);
  return (
    <Card title="通知" hint="通知偏好保存在本机；不含任何会话内容。">
      <Toggle checked={desktop} onChange={setDesktop} label="桌面通知" hint="运行完成、失败或需要审批时提醒" />
      <Toggle checked={approvals} onChange={setApprovals} label="审批提醒" hint="有新的待处理审批时置顶提示" />
      <Toggle checked={sound} onChange={setSound} label="提示音" />
    </Card>
  );
}

function ShortcutsSection() {
  const mac = typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);
  const mod = mac ? "⌘" : "Ctrl";
  const ITEMS = [
    { keys: `${mod} K`, desc: "聚焦当前模块搜索" },
    { keys: `${mod} N`, desc: "新建对话" },
    { keys: "Esc", desc: "关闭浮层或详情面板" },
    { keys: "Enter", desc: "发送消息" },
    { keys: "Shift Enter", desc: "输入换行" },
  ];
  return (
    <Card title="快捷键" hint="全局快捷键，键盘可完成导航与主要操作。">
      <div className="flex flex-col">
        {ITEMS.map((it) => (
          <div key={it.desc} className="flex items-center justify-between border-b py-2 last:border-0" style={{ borderColor: "var(--border)" }}>
            <span className="text-[13px]" style={{ color: "var(--fg)" }}>
              {it.desc}
            </span>
            <kbd
              className="rounded-[var(--radius-sm)] border px-2 py-0.5 font-mono text-[11px]"
              style={{ borderColor: "var(--border)", background: "var(--surface-inset)", color: "var(--fg-muted)" }}
            >
              {it.keys}
            </kbd>
          </div>
        ))}
      </div>
    </Card>
  );
}

function UpdateSection() {
  const [state, setState] = useState<{ loading: boolean; message?: string; tone?: "muted" | "warn" }>({
    loading: false,
  });
  const check = async () => {
    setState({ loading: true });
    try {
      const info = await ipc("app_check_update", undefined);
      // 如实表达：更新渠道未接入时不谎称"已是最新版本"（规范 §4.6 / 诚实原则）。
      if (info.configured === false) {
        setState({ loading: false, tone: "warn", message: "自动更新尚未接入，请通过官方渠道手动获取新版本。" });
      } else if (info.available) {
        setState({ loading: false, tone: "muted", message: `有可用更新：${info.version ?? "新版本"}` });
      } else {
        setState({ loading: false, tone: "muted", message: "已是最新版本" });
      }
    } catch (e) {
      setState({ loading: false, tone: "warn", message: toClientError(e).message });
    }
  };
  return (
    <Card title="更新" hint="更新通过签名渠道下发；下载与安装由 Rust Core 处理。签名自动更新为后续增量，当前尚未接入。">
      <div className="flex items-center gap-3">
        <Button size="sm" variant="secondary" disabled={state.loading} onClick={() => void check()}>
          <RefreshCw size={14} className={state.loading ? "animate-spin" : undefined} />
          检查更新
        </Button>
        {state.message && (
          <span
            className="text-[12px]"
            style={{ color: state.tone === "warn" ? "var(--warn)" : "var(--fg-muted)" }}
          >
            {state.message}
          </span>
        )}
      </div>
    </Card>
  );
}

function DiagnosticsSection() {
  const logout = useLogout();
  const activeId = useConnection((s) => s.activeConnectionId);
  const [state, setState] = useState<{ loading: boolean; message?: string }>({ loading: false });

  const exportDiag = async () => {
    setState({ loading: true });
    try {
      const r = await ipc("diagnostics_export", undefined);
      setState({ loading: false, message: `已导出到 ${r.path}（${r.bytes} 字节）` });
    } catch (e) {
      setState({ loading: false, message: toClientError(e).message });
    }
  };

  return (
    <>
      <Card title="诊断" hint="诊断包已脱敏，不含凭据、令牌或可复制的敏感字段。">
        <div className="flex items-center gap-3">
          <Button size="sm" variant="secondary" disabled={state.loading} onClick={() => void exportDiag()}>
            导出诊断包
          </Button>
          {state.message && (
            <span className="text-[12px]" style={{ color: "var(--fg-muted)" }}>
              {state.message}
            </span>
          )}
        </div>
      </Card>

      <section
        className="rounded-[var(--radius-lg)] border p-4"
        style={{ borderColor: "var(--danger)", background: "var(--surface-overlay)" }}
      >
        <h2 className="text-[13px] font-semibold" style={{ color: "var(--fg)" }}>
          危险操作
        </h2>
        <p className="mt-1 text-[12px]" style={{ color: "var(--fg-muted)" }}>
          以下操作与常规设置分离，请谨慎执行。
        </p>
        <div className="mt-3 flex flex-col gap-1">
          <Button
            size="sm"
            variant="dangerGhost"
            className="self-start"
            disabled={!activeId}
            onClick={() => activeId && logout.mutate(activeId)}
          >
            退出当前连接登录
          </Button>
        </div>
      </section>
    </>
  );
}

function AboutSection() {
  return (
    <Card title="关于 Vanta Desktop">
      <div className="flex flex-col gap-1 text-[12px]" style={{ color: "var(--fg-muted)" }}>
        <p>Vanta — 授权范围内的单兵作战 Agent 平台（代码审计 / 侦察 / 渗透）。</p>
        <p>Tauri 2 瘦客户端：Rust Core 持有连接与凭据，WebView 只负责展示与输入。</p>
        <p className="mt-2 font-mono" style={{ color: "var(--fg-subtle)" }}>
          desktop · v0.0.0
        </p>
      </div>
    </Card>
  );
}
