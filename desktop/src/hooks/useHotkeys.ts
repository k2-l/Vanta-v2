/**
 * 全局快捷键（规范 §5）：
 * - ⌘/Ctrl + K 聚焦当前模块搜索
 * - ⌘/Ctrl + N 新建对话
 * - Esc 关闭浮层或详情
 *
 * 通过自定义事件与当前挂载的模块解耦：ContextRail 监听 focus-search，
 * 对话页监听 new-chat。Esc 优先交给已打开的浮层（Radix 自行处理），
 * 无浮层时关闭当前模块详情。
 */

import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useUi, type ModuleId } from "@/stores/ui";

export const FOCUS_SEARCH_EVENT = "vanta:focus-search";
export const NEW_CHAT_EVENT = "vanta:new-chat";

export function moduleFromPath(pathname: string): ModuleId {
  const seg = pathname.split("/").filter(Boolean)[0];
  const known: ModuleId[] = ["chat", "runs", "approvals", "artifacts", "capabilities", "settings"];
  return (known as string[]).includes(seg) ? (seg as ModuleId) : "chat";
}

export function useHotkeys(): void {
  const navigate = useNavigate();
  const location = useLocation();
  const setDetailOpen = useUi((s) => s.setDetailOpen);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const mod = event.metaKey || event.ctrlKey;
      const key = event.key.toLowerCase();

      if (mod && key === "k") {
        event.preventDefault();
        window.dispatchEvent(new CustomEvent(FOCUS_SEARCH_EVENT));
        return;
      }
      if (mod && key === "n") {
        event.preventDefault();
        if (moduleFromPath(location.pathname) !== "chat") {
          // 用路由 state 把意图交给即将挂载的 ChatPage，避免导航期间事件丢失。
          navigate("/chat", { state: { newChat: true } });
        } else {
          window.dispatchEvent(new CustomEvent(NEW_CHAT_EVENT));
        }
        return;
      }
      if (key === "escape") {
        // 有浮层时交给浮层自身（Radix 监听 document 并阻止冒泡）。
        if (document.querySelector('[role="dialog"],[role="alertdialog"]')) return;
        setDetailOpen(moduleFromPath(location.pathname), false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [navigate, location.pathname, setDetailOpen]);
}
