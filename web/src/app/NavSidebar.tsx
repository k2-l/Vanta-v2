/**
 * Left nav sidebar.
 * - chat mode: 200px wide, shows logo text + session list
 * - other modes: 72px icon-only
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/shared/lib/api";
import { useAuth } from "@/store/auth";
import { useChat } from "@/store/chat";
import { useSessions } from "@/store/sessions";
import { MarkdownPreview } from "@/shared/components/MarkdownPreview";
import { MarkdownEditor } from "@/shared/components/MarkdownEditor";
import type { Module } from "@/app/App";

const NAV_ITEMS: { key: Module; icon: string; label: string }[] = [
  { key: "chat",      icon: "◈", label: "对话"  },
  { key: "agent",     icon: "◉", label: "Agent" },
  { key: "skill",     icon: "◎", label: "技能"  },
  { key: "kb",        icon: "◷", label: "知识库" },
  { key: "memory",    icon: "◌", label: "记忆"  },
  { key: "container", icon: "▣", label: "容器"  },
  { key: "mcp",       icon: "◆", label: "MCP"  },
  { key: "config",    icon: "◧", label: "配置"  },
];

interface Props {
  activeModule: Module;
  onModuleChange: (m: Module) => void;
}

export function NavSidebar({ activeModule, onModuleChange }: Props) {
  const logout = useAuth((s) => s.logout);
  const sessions = useSessions((s) => s.sessions);
  const currentId = useChat((s) => s.currentSessionId);
  const setSessions = useSessions((s) => s.setSessions);
  const setCurrentSession = useChat((s) => s.setCurrentSession);
  const setMessages = useChat((s) => s.setMessages);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [sessionQuery, setSessionQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  // Cmd/Ctrl+K 聚焦 session 搜索框
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  const [showProfile, setShowProfile] = useState(false);
  const [profileText, setProfileText] = useState("");
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileTab, setProfileTab] = useState<"edit" | "preview">("edit");

  async function openProfile() {
    setProfileError(null);
    try { setProfileText((await api.getProfile()).content); } catch { setProfileText(""); }
    setProfileTab("edit");
    setShowProfile(true);
  }
  async function saveProfile() {
    setProfileSaving(true);
    setProfileError(null);
    try {
      await api.putProfile(profileText);
      setShowProfile(false);
    } catch (e) {
      setProfileError(`保存失败：${e}`);
    }
    setProfileSaving(false);
  }

  async function saveTitle(id: string) {
    const title = editingTitle.trim();
    setEditingId(null);
    if (!title) return;
    try {
      const updated = await api.patchSession(id, title);
      setSessions(sessions.map((s) => (s.id === id ? updated : s)));
    } catch {
      // 保存失败：无需额外提示，原标题在 sessions 里未变
      console.error("session rename failed");
    }
  }

  // 左栏布局恒定展开（宽度/标签/对齐不再随模块在 200↔72 间 morph，去掉切换抖动）；
  // isChat 保留旧名但恒为 true，所有布局分支恒取"展开"态。会话列表另用 showSessions 仅 chat 显示。
  const isChat = true;
  const showSessions = activeModule === "chat";
  const sidebarWidth = 168;   // 恒定宽度（原 200，收窄一些）

  // 用 ref 持有 currentId，避免 refresh 每次 session 切换都重建，
  // 防止 useEffect 反复触发 → 重复调 listSessions
  const currentIdRef = useRef(currentId);
  useEffect(() => { currentIdRef.current = currentId; }, [currentId]);

  const refresh = useCallback(async () => {
    try {
      const list = await api.listSessions();
      setSessions(list);
      if (!currentIdRef.current && list.length > 0) {
        await switchTo(list[0].id);
      } else if (list.length === 0) {
        const created = await api.createSession();
        setSessions([created]);
        await switchTo(created.id);
      }
    } catch (e) {
      console.error("sessions load failed", e);
    }
  // setSessions/switchTo 是稳定的 Zustand selector，不需要在依赖里
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // turn 结束后延迟刷新 session 列表，捕获 titler 异步生成的标题
  const inFlight = useChat((s) => s.turn.inFlight);
  const prevInFlight = useRef(false);
  useEffect(() => {
    if (prevInFlight.current && !inFlight) {
      // 延迟 2s 等 titler 完成写入
      const t = setTimeout(() => { refresh(); }, 2000);
      return () => clearTimeout(t);
    }
    prevInFlight.current = inFlight;
    return undefined;
  }, [inFlight, refresh]);

  async function switchTo(id: string) {
    setCurrentSession(id);
    onModuleChange("chat");
    try {
      const msgs = await api.getMessages(id);
      setMessages(msgs);
    } catch (e) {
      console.error("getMessages failed", e);
    }
  }

  async function createNew() {
    try {
      const s = await api.createSession();
      setSessions([s, ...sessions]);
      await switchTo(s.id);
    } catch (e) {
      console.error("createSession failed", e);
    }
  }

  async function remove(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    await api.deleteSession(id);
    const newList = sessions.filter((s) => s.id !== id);
    setSessions(newList);
    if (id === currentId) {
      if (newList.length > 0) await switchTo(newList[0].id);
      else setCurrentSession(null);
    }
  }

  return (
    <aside style={{
      width: sidebarWidth,
      transition: "width 0.2s",
      background: "#FFFFFF",
      borderRight: "1px solid #E2E5EA",
      display: "flex",
      flexDirection: "column",
      alignItems: isChat ? "stretch" : "center",
      paddingTop: 20,
      paddingBottom: 16,
      flexShrink: 0,
      overflow: "hidden",
    }}>
      {/* Logo row */}
      <div style={{
        display: "flex",
        flexDirection: isChat ? "row" : "column",
        alignItems: "center",
        marginBottom: 28,
        gap: 6,
        padding: isChat ? "0 16px" : "0",
      }}>
        <span style={{ fontSize: 22, color: "#4F6EF7" }}>⬡</span>
        {isChat && (
          <span style={{ fontSize: 9, letterSpacing: 3, color: "#9BA3AF", fontWeight: 700 }}>
            NEXUS
          </span>
        )}
      </div>

      {/* Nav items */}
      <nav style={{ display: "flex", flexDirection: "column", gap: 4, width: "100%", alignItems: isChat ? "stretch" : "center" }}>
        {NAV_ITEMS.map((item) => {
          const isActive = activeModule === item.key;

          if (item.key === "chat") {
            return (
              <div key="chat">
                <button
                  onClick={() => onModuleChange("chat")}
                  style={{
                    display: "flex",
                    flexDirection: "row",
                    alignItems: "center",
                    justifyContent: isChat ? "flex-start" : "center",
                    gap: isChat ? 8 : 0,
                    padding: isChat ? "10px 16px" : "10px 0",
                    background: isActive ? "#4F6EF711" : "transparent",
                    border: "none",
                    cursor: "pointer",
                    color: isActive ? "#4F6EF7" : "#9BA3AF",
                    width: "100%",
                    transition: "all 0.15s",
                    fontFamily: "inherit",
                  }}
                >
                  <span style={{ fontSize: 16 }}>{item.icon}</span>
                  {isChat && <span style={{ fontSize: 12, fontWeight: 600 }}>对话</span>}
                </button>

                {/* Session list — only in chat mode */}
                {showSessions && (
                  <div style={{ display: "flex", flexDirection: "column" }}>
                    {sessions.length > 3 && (
                      <div style={{ padding: "6px 16px 4px" }}>
                        <input
                          ref={searchRef}
                          value={sessionQuery}
                          onChange={(e) => setSessionQuery(e.target.value)}
                          onKeyDown={(e) => e.key === "Escape" && setSessionQuery("")}
                          placeholder="搜索会话… (⌘K)"
                          style={{
                            width: "100%", boxSizing: "border-box", fontSize: 11,
                            background: "#F4F5F7", border: "1px solid #E2E5EA",
                            borderRadius: 6, padding: "5px 10px", outline: "none",
                            color: "#374151", fontFamily: "inherit",
                          }}
                        />
                      </div>
                    )}
                    {sessions
                      .filter((s) => !sessionQuery || s.title.toLowerCase().includes(sessionQuery.toLowerCase()) || s.id.includes(sessionQuery))
                      .map((sess) => {
                      const isSel = sess.id === currentId;
                      return (
                        <div
                          key={sess.id}
                          onClick={() => switchTo(sess.id)}
                          onMouseEnter={() => setHoveredId(sess.id)}
                          onMouseLeave={() => setHoveredId(null)}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 6,
                            padding: "7px 16px 7px 36px",
                            cursor: "pointer",
                            background: isSel ? "#4F6EF711" : hoveredId === sess.id ? "#F4F5F7" : "transparent",
                            borderRight: `2px solid ${isSel ? "#4F6EF7" : "transparent"}`,
                            transition: "all 0.12s",
                          }}
                        >
                          {editingId === sess.id ? (
                            <input
                              autoFocus
                              value={editingTitle}
                              onChange={(e) => setEditingTitle(e.target.value)}
                              onBlur={() => saveTitle(sess.id)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") saveTitle(sess.id);
                                if (e.key === "Escape") setEditingId(null);
                                e.stopPropagation();
                              }}
                              onClick={(e) => e.stopPropagation()}
                              style={{
                                flex: 1, fontSize: 11, fontFamily: "inherit",
                                background: "#F0F4FF", border: "1px solid #4F6EF7",
                                borderRadius: 4, padding: "1px 4px",
                                color: "#1A1D23", outline: "none", minWidth: 0,
                              }}
                            />
                          ) : (
                            <span
                              style={{
                                flex: 1, fontSize: 11,
                                color: isSel ? "#4F6EF7" : "#6B7280",
                                overflow: "hidden", textOverflow: "ellipsis",
                                whiteSpace: "nowrap", fontWeight: isSel ? 600 : 400,
                              }}
                              onDoubleClick={(e) => {
                                e.stopPropagation();
                                setEditingId(sess.id);
                                setEditingTitle(sess.title);
                              }}
                              title="双击编辑标题"
                            >
                              {sess.title}
                            </span>
                          )}
                          <button
                            onClick={(e) => remove(sess.id, e)}
                            title="删除会话"
                            onMouseEnter={(e) => {
                              e.currentTarget.style.background = "#FEE2E2";
                              e.currentTarget.style.color = "#EF4444";
                            }}
                            onMouseLeave={(e) => {
                              e.currentTarget.style.background = "transparent";
                              e.currentTarget.style.color = "#9BA3AF";
                            }}
                            style={{
                              display: hoveredId === sess.id ? "flex" : "none",
                              alignItems: "center",
                              justifyContent: "center",
                              width: 18,
                              height: 18,
                              background: "transparent",
                              border: "none",
                              borderRadius: 4,
                              cursor: "pointer",
                              color: "#9BA3AF",
                              fontSize: 10,
                              padding: 0,
                              flexShrink: 0,
                              fontFamily: "inherit",
                              transition: "background 0.12s, color 0.12s",
                            }}
                          >
                            ✕
                          </button>
                        </div>
                      );
                    })}
                    <button
                      onClick={createNew}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        padding: "7px 16px 7px 36px",
                        background: "transparent",
                        border: "none",
                        cursor: "pointer",
                        color: "#9BA3AF",
                        fontSize: 11,
                        fontFamily: "inherit",
                        textAlign: "left",
                      }}
                    >
                      ＋ 新建对话
                    </button>
                  </div>
                )}
              </div>
            );
          }

          return (
            <button
              key={item.key}
              onClick={() => onModuleChange(item.key)}
              style={{
                display: "flex",
                flexDirection: isChat ? "row" : "column",
                alignItems: "center",
                justifyContent: isChat ? "flex-start" : "center",
                gap: isChat ? 8 : 3,
                padding: isChat ? "10px 16px" : "10px 0",
                background: isActive ? "#4F6EF711" : "transparent",
                border: "none",
                cursor: "pointer",
                color: isActive ? "#4F6EF7" : "#9BA3AF",
                width: "100%",
                transition: "all 0.15s",
                fontFamily: "inherit",
              }}
            >
              <span style={{ fontSize: 16 }}>{item.icon}</span>
              {isChat
                ? <span style={{ fontSize: 12 }}>{item.label}</span>
                : <span style={{ fontSize: 9, letterSpacing: 1 }}>{item.label}</span>
              }
            </button>
          );
        })}
      </nav>

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Bottom: status + logout */}
      <div style={{
        display: "flex",
        flexDirection: "column",
        alignItems: isChat ? "flex-start" : "center",
        gap: 4,
        padding: isChat ? "0 16px" : "0",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: "#22C55E",
            boxShadow: "0 0 6px #22C55E88",
            display: "block",
            flexShrink: 0,
          }} />
          {isChat && <span style={{ fontSize: 10, color: "#9BA3AF" }}>Master Online</span>}
        </div>
        <button
          onClick={openProfile}
          style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "6px 0", width: "100%", background: "transparent",
            border: "none", cursor: "pointer", color: "#6B7280",
            opacity: 0.8, fontFamily: "inherit",
          }}
        >
          {isChat && <span style={{ fontSize: 11 }}>✎ 编辑 Profile</span>}
          {!isChat && <span style={{ fontSize: 12 }}>✎</span>}
        </button>
        <button
          onClick={logout}
          style={{
            display: "flex",
            flexDirection: isChat ? "row" : "column",
            alignItems: "center",
            justifyContent: isChat ? "flex-start" : "center",
            gap: isChat ? 6 : 3,
            padding: "8px 0",
            width: "100%",
            background: "transparent",
            border: "none",
            cursor: "pointer",
            color: "#EF4444",
            opacity: 0.7,
            transition: "opacity 0.15s",
            fontFamily: "inherit",
          }}
        >
          {isChat
            ? <span style={{ fontSize: 11 }}>退出</span>
            : <span style={{ fontSize: 9, letterSpacing: 1 }}>退出</span>
          }
        </button>
      </div>

      {/* Profile 编辑 Modal */}
      {showProfile && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.25)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 300 }}>
          <div style={{ background: "#fff", border: "1px solid #E2E5EA", borderRadius: 14, width: "100%", maxWidth: 560, boxShadow: "0 24px 64px rgba(0,0,0,0.12)", display: "flex", flexDirection: "column", maxHeight: "75vh" }}>
            <div style={{ display: "flex", alignItems: "center", padding: "16px 24px", borderBottom: "1px solid #E2E5EA", flexShrink: 0 }}>
              <span style={{ flex: 1, fontSize: 14, fontWeight: 700, color: "#1A1D23" }}>编辑用户 Profile</span>
              <div style={{ display: "flex", gap: 2, marginRight: 12 }}>
                {(["edit", "preview"] as const).map((t) => (
                  <button key={t} onClick={() => setProfileTab(t)}
                    style={{ fontSize: 11, padding: "4px 10px", borderRadius: 6, border: "none", cursor: "pointer", fontFamily: "inherit",
                      background: profileTab === t ? "#4F6EF718" : "transparent",
                      color: profileTab === t ? "#4F6EF7" : "#9BA3AF",
                    }}>
                    {t === "edit" ? "✎ 编辑" : "◉ 预览"}
                  </button>
                ))}
              </div>
              <button onClick={() => setShowProfile(false)} style={{ background: "none", border: "none", color: "#9BA3AF", cursor: "pointer", fontSize: 14 }}>✕</button>
            </div>
            <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
              {profileTab === "edit" ? (
                <MarkdownEditor
                  value={profileText}
                  onChange={setProfileText}
                  style={{ flex: 1, minHeight: 260, padding: "16px 24px" }}
                />
              ) : (
                profileText
                  ? <MarkdownPreview content={profileText} style={{ flex: 1, overflowY: "auto", padding: "16px 24px" }} />
                  : <div style={{ flex: 1, overflowY: "auto", padding: "16px 24px" }}>
                      <span style={{ color: "#C0C5CE", fontStyle: "italic" }}>空 profile…</span>
                    </div>
              )}
            </div>
            {profileError && (
              <div style={{ padding: "6px 24px", background: "#FEF2F2", borderTop: "1px solid #FECACA" }}>
                <span style={{ color: "#DC2626", fontSize: 11 }}>{profileError}</span>
              </div>
            )}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, padding: "14px 24px", borderTop: "1px solid #E2E5EA", flexShrink: 0 }}>
              <button onClick={() => setShowProfile(false)} style={{ fontSize: 12, padding: "7px 16px", borderRadius: 8, background: "transparent", border: "1px solid #E2E5EA", color: "#6B7280", cursor: "pointer", fontFamily: "inherit" }}>取消</button>
              <button onClick={saveProfile} disabled={profileSaving} style={{ fontSize: 12, padding: "8px 18px", borderRadius: 8, background: "#4F6EF718", border: "1px solid #4F6EF744", color: "#4F6EF7", cursor: profileSaving ? "wait" : "pointer", fontFamily: "inherit" }}>
                {profileSaving ? "保存中…" : "保存"}
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
