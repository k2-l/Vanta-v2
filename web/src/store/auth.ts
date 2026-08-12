/**
 * 鉴权状态：token 持久化在 localStorage。
 *
 * - login: 调 /auth/login 拿 token，保存
 * - logout: 清空 token
 * - isAuthed: 派生：token 存在 + 未过期
 * - 401 全局处理：fetch 包装器在收到 401 时调 forceLogout
 */

import { create } from "zustand";

const KEY = "harness.auth";

type Stored = { token: string; expiresAt: string };

function loadStored(): Stored | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Stored;
    if (!parsed.token || !parsed.expiresAt) return null;
    if (new Date(parsed.expiresAt).getTime() <= Date.now()) {
      localStorage.removeItem(KEY);
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function saveStored(s: Stored | null) {
  if (s) localStorage.setItem(KEY, JSON.stringify(s));
  else localStorage.removeItem(KEY);
}

interface AuthState {
  token: string | null;
  expiresAt: string | null;
  loginError: string | null;
  loading: boolean;
  login: (password: string, baseUrl: string) => Promise<boolean>;
  logout: () => void;
  forceLogout: (reason?: string) => void;
}

export const useAuth = create<AuthState>((set) => {
  const stored = loadStored();
  return {
    token: stored?.token ?? null,
    expiresAt: stored?.expiresAt ?? null,
    loginError: null,
    loading: false,

    login: async (password, baseUrl) => {
      set({ loading: true, loginError: null });
      try {
        const resp = await fetch(`${baseUrl}/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password }),
        });
        if (!resp.ok) {
          const data = await resp.json().catch(() => ({ detail: resp.statusText }));
          throw new Error(data.detail || `登录失败: ${resp.status}`);
        }
        const data = (await resp.json()) as {
          token: string;
          expires_at: string;
        };
        saveStored({ token: data.token, expiresAt: data.expires_at });
        set({
          token: data.token,
          expiresAt: data.expires_at,
          loading: false,
          loginError: null,
        });
        return true;
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        set({ loading: false, loginError: msg });
        return false;
      }
    },

    logout: () => {
      saveStored(null);
      set({ token: null, expiresAt: null, loginError: null });
    },

    forceLogout: (reason) => {
      saveStored(null);
      set({
        token: null,
        expiresAt: null,
        loginError: reason || "会话已过期，请重新登录",
      });
    },
  };
});

/** 当前是否已登录（同步读取一次）。 */
export function isAuthed(): boolean {
  const { token, expiresAt } = useAuth.getState();
  if (!token || !expiresAt) return false;
  return new Date(expiresAt).getTime() > Date.now();
}

/** 给 fetch 用的 Authorization 头。 */
export function authHeader(): Record<string, string> {
  const t = useAuth.getState().token;
  return t ? { Authorization: `Bearer ${t}` } : {};
}
