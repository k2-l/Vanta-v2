import { useState } from "react";
import { useAuth } from "@/store/auth";
import { API_BASE } from "@/shared/lib/api";

export function LoginPage() {
  const [pwd, setPwd] = useState("");
  const [show, setShow] = useState(false);
  const login = useAuth((s) => s.login);
  const error = useAuth((s) => s.loginError);
  const loading = useAuth((s) => s.loading);

  async function submit() {
    if (!pwd.trim() || loading) return;
    await login(pwd, API_BASE);
  }

  return (
    <div style={{
      display: "flex",
      height: "100vh",
      width: "100vw",
      alignItems: "center",
      justifyContent: "center",
      background: "#F4F5F7",
      fontFamily: "'SF Mono','JetBrains Mono','Fira Code',monospace",
    }}>
      <div style={{ width: 360, display: "flex", flexDirection: "column", gap: 0 }}>
        {/* Logo */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginBottom: 36, gap: 8 }}>
          <span style={{ fontSize: 36, color: "#4F6EF7" }}>⬡</span>
          <span style={{ fontSize: 11, letterSpacing: 4, color: "#9BA3AF", fontWeight: 700 }}>NEXUS</span>
          <span style={{ fontSize: 12, color: "#C0C5CE", marginTop: 4 }}>Agent 系统控制台</span>
        </div>

        {/* Card */}
        <div style={{
          background: "#FFFFFF",
          border: "1px solid #E2E5EA",
          borderRadius: 14,
          padding: "32px 28px",
          boxShadow: "0 4px 24px rgba(0,0,0,0.06)",
          display: "flex",
          flexDirection: "column",
          gap: 20,
        }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span style={{ fontSize: 10, color: "#9BA3AF", letterSpacing: 1.5, textTransform: "uppercase" }}>
              访问密码
            </span>
            <div style={{ position: "relative" }}>
              <input
                type={show ? "text" : "password"}
                value={pwd}
                autoFocus
                onChange={(e) => { setPwd(e.target.value); }}
                onKeyDown={(e) => e.key === "Enter" && submit()}
                placeholder="输入密码…"
                style={{
                  width: "100%",
                  boxSizing: "border-box",
                  background: "#F9FAFB",
                  border: `1px solid ${error ? "#EF4444" : "#E2E5EA"}`,
                  borderRadius: 8,
                  padding: "11px 40px 11px 14px",
                  color: "#1A1D23",
                  fontSize: 13,
                  outline: "none",
                  fontFamily: "inherit",
                  transition: "border-color 0.15s",
                }}
              />
              <button
                onClick={() => setShow((v) => !v)}
                style={{
                  position: "absolute",
                  right: 12,
                  top: "50%",
                  transform: "translateY(-50%)",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  color: "#9BA3AF",
                  fontSize: 12,
                  padding: 0,
                  fontFamily: "inherit",
                }}
              >
                {show ? "隐藏" : "显示"}
              </button>
            </div>
            {error && <span style={{ fontSize: 11, color: "#EF4444" }}>{error}</span>}
          </div>

          <button
            onClick={submit}
            disabled={loading || !pwd.trim()}
            style={{
              padding: "12px 0",
              borderRadius: 8,
              border: "none",
              cursor: loading || !pwd.trim() ? "default" : "pointer",
              background: loading || !pwd.trim() ? "#E2E5EA" : "#4F6EF7",
              color: loading || !pwd.trim() ? "#9BA3AF" : "#FFFFFF",
              fontSize: 13,
              fontWeight: 600,
              fontFamily: "inherit",
              transition: "all 0.15s",
              letterSpacing: 0.5,
            }}
          >
            {loading ? "验证中…" : "进入系统"}
          </button>
        </div>

        <div style={{ textAlign: "center", marginTop: 16, fontSize: 10, color: "#C0C5CE" }}>
          JWT · 24h 有效期
        </div>
      </div>
    </div>
  );
}
