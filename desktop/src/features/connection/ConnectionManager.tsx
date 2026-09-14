import { useForm } from "react-hook-form";
import { useState } from "react";
import { Button } from "@/components/Button";
import { EmptyState } from "@/components/EmptyState";
import { useConnections, useSaveConnection, useDeleteConnection, useTestConnection } from "./useConnections";
import { useActivateConnection, useLogin } from "./useActivate";
import { useConnection } from "@/stores/connection";
import { toClientError, type ClientError } from "@/contracts/errors";
import type { HealthResult } from "@/contracts/connection";

type DraftForm = { label: string; baseUrl: string };

/**
 * 连接管理器——添加服务器 / 测试连接 / 激活 / 登录（方案 §9、G0 完成标准）。
 * 密码只作为一次性 IPC 入参传给 Rust，前端不持久化、不回显。
 */
export function ConnectionManager() {
  const { data: connections = [], isLoading } = useConnections();
  const save = useSaveConnection();
  const del = useDeleteConnection();
  const test = useTestConnection();
  const activate = useActivateConnection();
  const login = useLogin();
  const active = useConnection((s) => s.activeConnectionId);
  const auth = useConnection((s) => s.auth);

  const { register, handleSubmit, reset, formState } = useForm<DraftForm>({
    defaultValues: { label: "", baseUrl: "http://127.0.0.1:8765" },
  });
  const [testResult, setTestResult] = useState<HealthResult | null>(null);
  const [error, setError] = useState<ClientError | null>(null);
  const [password, setPassword] = useState("");

  const onSave = handleSubmit(async (form) => {
    setError(null);
    try {
      await save.mutateAsync({ label: form.label || form.baseUrl, baseUrl: form.baseUrl });
      reset();
    } catch (e) {
      setError(toClientError(e));
    }
  });

  return (
    <div className="flex flex-col gap-6 max-w-2xl">
      {/* 新增连接 */}
      <section
        className="rounded-lg border p-4"
        style={{ borderColor: "var(--border)", background: "var(--bg-elevated)" }}
      >
        <h2 className="text-sm font-semibold mb-3">添加服务器</h2>
        <form onSubmit={onSave} className="flex flex-col gap-3">
          <Field label="名称">
            <input className={inputCls} placeholder="例如：本地后端" {...register("label")} />
          </Field>
          <Field label="后端地址">
            <input
              className={inputCls}
              placeholder="http://127.0.0.1:8765"
              {...register("baseUrl", { required: true })}
            />
          </Field>
          <div className="flex items-center gap-2">
            <Button type="submit" size="sm" disabled={save.isPending || !formState.isValid}>
              保存
            </Button>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={test.isPending}
              onClick={async () => {
                setError(null);
                setTestResult(null);
                try {
                  const r = await test.mutateAsync({
                    draft: { label: "draft", baseUrl: (document.querySelector<HTMLInputElement>("[name=baseUrl]")?.value ?? "").trim() },
                  });
                  setTestResult(r);
                } catch (e) {
                  setError(toClientError(e));
                }
              }}
            >
              测试连接
            </Button>
            {testResult && (
              <span className="text-xs" style={{ color: testResult.ok ? "var(--ok)" : "var(--danger)" }}>
                {testResult.ok ? `可达 · ${testResult.serverVersion ?? "?"} · ${testResult.latencyMs ?? "?"}ms` : "不可达"}
              </span>
            )}
          </div>
          {error && (
            <p className="text-xs" style={{ color: "var(--danger)" }}>
              {error.message}
            </p>
          )}
        </form>
      </section>

      {/* 连接列表 */}
      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">已保存的服务器</h2>
        {isLoading ? (
          <p className="text-xs" style={{ color: "var(--fg-muted)" }}>
            加载中…
          </p>
        ) : connections.length === 0 ? (
          <EmptyState title="尚无服务器" hint="添加一个 Vanta 后端地址以开始。" />
        ) : (
          connections.map((c) => (
            <div
              key={c.id}
              className="flex items-center justify-between rounded-md border px-4 py-3"
              style={{
                borderColor: active === c.id ? "var(--accent)" : "var(--border)",
                background: "var(--bg-elevated)",
              }}
            >
              <div className="min-w-0">
                <p className="text-sm font-medium truncate">{c.label}</p>
                <p className="text-xs truncate" style={{ color: "var(--fg-muted)" }}>
                  {c.baseUrl}
                  {c.lastKnownVersion && ` · ${c.lastKnownVersion}`}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Button size="sm" variant="secondary" onClick={() => activate.mutate(c.id)} disabled={activate.isPending}>
                  {active === c.id ? "已激活" : "激活"}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => del.mutate(c.id)} disabled={del.isPending}>
                  删除
                </Button>
              </div>
            </div>
          ))
        )}
      </section>

      {/* 登录（激活后且未认证） */}
      {active && !auth.authenticated && (
        <section
          className="rounded-lg border p-4"
          style={{ borderColor: "var(--border)", background: "var(--bg-elevated)" }}
        >
          <h2 className="text-sm font-semibold mb-3">登录</h2>
          <div className="flex items-center gap-2">
            <input
              type="password"
              className={inputCls}
              placeholder="访问口令"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <Button
              size="sm"
              disabled={login.isPending || !password}
              onClick={async () => {
                await login.mutateAsync({ connectionId: active, password });
                setPassword("");
              }}
            >
              登录
            </Button>
          </div>
          <p className="text-xs mt-2" style={{ color: "var(--fg-subtle)" }}>
            口令仅一次性传给本地 Rust Core 换取令牌；WebView 不保存明文凭据。
          </p>
        </section>
      )}

      {active && auth.authenticated && (
        <p className="text-xs" style={{ color: "var(--ok)" }}>
          已登录{auth.expiresAt ? ` · 令牌到期 ${new Date(auth.expiresAt).toLocaleString()}` : ""}
        </p>
      )}
    </div>
  );
}

const inputCls =
  "flex-1 h-9 px-3 rounded-md border text-sm bg-[var(--bg-inset)] border-[var(--border)] outline-none focus:border-[var(--accent)]";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs" style={{ color: "var(--fg-muted)" }}>
        {label}
      </span>
      {children}
    </label>
  );
}
