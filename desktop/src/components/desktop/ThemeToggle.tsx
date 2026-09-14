/**
 * 主题切换——在 深色 / 浅色 / 跟随系统 之间循环（规范 §3.1 / §4.6）。
 * 设置页提供完整三选，标题栏提供快捷循环。
 */

import { Monitor, Moon, Sun } from "lucide-react";
import { useUi, type ThemePref } from "@/stores/ui";

const NEXT: Record<ThemePref, ThemePref> = { dark: "light", light: "system", system: "dark" };
const META: Record<ThemePref, { label: string; icon: typeof Moon }> = {
  dark: { label: "深色", icon: Moon },
  light: { label: "浅色", icon: Sun },
  system: { label: "跟随系统", icon: Monitor },
};

export function ThemeToggle() {
  const theme = useUi((s) => s.theme);
  const setTheme = useUi((s) => s.setTheme);
  const { label, icon: Icon } = META[theme];

  return (
    <button
      type="button"
      aria-label={`主题：${label}（点击切换）`}
      title={`主题：${label}`}
      onClick={() => setTheme(NEXT[theme])}
      className="no-drag grid h-7 w-7 place-items-center rounded-[var(--radius-sm)] transition-colors hover:bg-[var(--surface-inset)]"
      style={{ color: "var(--fg-muted)" }}
    >
      <Icon size={15} />
    </button>
  );
}
