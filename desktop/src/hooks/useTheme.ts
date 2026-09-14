/**
 * 主题应用（规范 §3.1）。默认深色；`system` 解析为显式 data-theme，
 * 使 tokens.css 只需维护两套色板，并跟随系统实时切换。
 */

import { useEffect } from "react";
import { useUi } from "@/stores/ui";

function systemPrefersLight(): boolean {
  return typeof matchMedia !== "undefined" && matchMedia("(prefers-color-scheme: light)").matches;
}

export function resolveTheme(pref: string): "dark" | "light" {
  if (pref === "light") return "light";
  if (pref === "dark") return "dark";
  return systemPrefersLight() ? "light" : "dark";
}

/** 挂载在应用根部：把 theme 偏好落到 <html data-theme>，并在 system 下监听变化。 */
export function useApplyTheme(): void {
  const theme = useUi((s) => s.theme);

  useEffect(() => {
    const apply = () => {
      document.documentElement.setAttribute("data-theme", resolveTheme(theme));
    };
    apply();
    if (theme !== "system" || typeof matchMedia === "undefined") return;
    const mq = matchMedia("(prefers-color-scheme: light)");
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [theme]);
}
