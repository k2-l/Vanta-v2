import * as Dialog from "@radix-ui/react-dialog";
import { useState, type ReactNode } from "react";
import { FlaskConical, Plug, Save, Trash2, X } from "lucide-react";
import { Button } from "@/components/Button";
import type {
  McpServerCreateInput,
  McpServerPatchInput,
  McpServerWire,
} from "@/contracts/mcp";
import { toClientError } from "@/contracts/errors";
import {
  useCreateMcpServer,
  useDeleteMcpServer,
  useMcpServer,
  useTestMcpServer,
  useUpdateMcpServer,
} from "./useMcpManagement";

const controlClass =
  "h-8 w-full rounded-[var(--radius-sm)] border px-2.5 text-[12px] outline-none focus:border-[var(--accent-line)] disabled:opacity-50";
const controlStyle = {
  background: "var(--surface-inset)",
  borderColor: "var(--border)",
  color: "var(--fg)",
};

type McpDraft = {
  name: string;
  command: string;
  args: string;
  env: string;
  enabled: boolean;
  replaceEnv: boolean;
};

function fromServer(server?: McpServerWire): McpDraft {
  return {
    name: server?.name ?? "",
    command: server?.command ?? "",
    args: server?.args.join("\n") ?? "",
    env: "",
    enabled: server?.enabled ?? true,
    replaceEnv: !server,
  };
}

function parseLines(value: string): string[] {
  return value.split("\n").map((line) => line.trim()).filter(Boolean);
}

function parseEnv(value: string): Record<string, string> {
  const env: Record<string, string> = {};
  for (const rawLine of value.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    const separator = line.indexOf("=");
    if (separator < 1) throw new Error(`环境变量格式错误：${line}（应为 KEY=value）`);
    const key = line.slice(0, separator).trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) throw new Error(`环境变量名不合法：${key}`);
    env[key] = line.slice(separator + 1);
  }
  return env;
}

function quoteArgument(value: string): string {
  return /^[A-Za-z0-9_./:@%+=,-]+$/.test(value) ? value : `'${value.replaceAll("'", `'\\''`)}'`;
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-medium" style={{ color: "var(--fg-muted)" }}>{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[10px]" style={{ color: "var(--fg-subtle)" }}>{hint}</span>}
    </label>
  );
}

function Toggle({ checked, label, hint, onChange }: {
  checked: boolean;
  label: string;
  hint: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label
      className="flex cursor-pointer items-center justify-between gap-3 rounded-[var(--radius-sm)] border px-3 py-2"
      style={{ borderColor: checked ? "var(--accent)" : "var(--border)", background: checked ? "var(--accent-tint)" : "var(--surface-inset)" }}
    >
      <span>
        <span className="block text-[11px] font-medium" style={{ color: "var(--fg)" }}>{label}</span>
        <span className="block text-[10px]" style={{ color: "var(--fg-subtle)" }}>{hint}</span>
      </span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
    </label>
  );
}

export function McpServerDialog({ server, onClose }: { server?: McpServerWire; onClose: () => void }) {
  const create = useCreateMcpServer();
  const update = useUpdateMcpServer();
  const remove = useDeleteMcpServer();
  const test = useTestMcpServer();
  const detail = useMcpServer(server?.name);
  const [draft, setDraft] = useState<McpDraft>(() => fromServer(server));
  const [error, setError] = useState<string>();
  const [confirmSave, setConfirmSave] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const editing = Boolean(server);
  const busy = create.isPending || update.isPending || remove.isPending || test.isPending;
  const current = detail.data ?? server;
  const args = parseLines(draft.args);
  const commandPreview = [draft.command.trim(), ...args].filter(Boolean).map(quoteArgument).join(" ");

  const validate = () => {
    const name = draft.name.trim();
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(name) || name.includes("__")) {
      throw new Error("名称长度须为 1–64，仅允许字母、数字、点、下划线和连字符，且不能包含连续双下划线");
    }
    if (!draft.command.trim()) throw new Error("启动命令不能为空");
    if (draft.replaceEnv) parseEnv(draft.env);
  };

  const requestSave = () => {
    try {
      validate();
      setError(undefined);
      setConfirmSave(true);
    } catch (caught) {
      setError(toClientError(caught).message);
    }
  };

  const save = async () => {
    try {
      validate();
      setError(undefined);
      if (server) {
        const input: McpServerPatchInput = {
          command: draft.command.trim(),
          args,
          enabled: draft.enabled,
          confirm: true,
          ...(draft.replaceEnv ? { env: parseEnv(draft.env) } : {}),
        };
        await update.mutateAsync({ name: server.name, input });
      } else {
        const input: McpServerCreateInput = {
          name: draft.name.trim(),
          command: draft.command.trim(),
          args,
          env: parseEnv(draft.env),
          enabled: draft.enabled,
          confirm: true,
        };
        await create.mutateAsync(input);
      }
      onClose();
    } catch (caught) {
      setError(toClientError(caught).message);
      setConfirmSave(false);
    }
  };

  const deleteServer = async () => {
    if (!server) return;
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    try {
      setError(undefined);
      await remove.mutateAsync(server.name);
      onClose();
    } catch (caught) {
      setError(toClientError(caught).message);
      setConfirmDelete(false);
    }
  };

  const testServer = async () => {
    if (!server) return;
    setError(undefined);
    test.reset();
    try {
      await test.mutateAsync(server.name);
    } catch (caught) {
      setError(toClientError(caught).message);
    }
  };

  const envKeys = draft.replaceEnv
    ? Object.keys(parseEnvSafely(draft.env))
    : current?.env_keys ?? [];

  return (
    <Dialog.Root open onOpenChange={(open) => !open && !busy && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-[2px]" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 flex max-h-[90vh] w-[min(760px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col rounded-[var(--radius-lg)] border shadow-2xl outline-none"
          style={{ background: "var(--surface-overlay)", borderColor: "var(--border)" }}
        >
          <div className="flex items-start gap-3 border-b px-5 py-4" style={{ borderColor: "var(--border)" }}>
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[var(--radius)]" style={{ background: "var(--accent-tint)", color: "var(--accent)" }}>
              <Plug size={17} />
            </span>
            <div className="min-w-0 flex-1">
              <Dialog.Title className="text-[15px] font-semibold" style={{ color: "var(--fg)" }}>{editing ? `管理 ${server?.name}` : "创建 MCP Server"}</Dialog.Title>
              <Dialog.Description className="mt-1 text-[11px]" style={{ color: "var(--fg-muted)" }}>通过后端 stdio 管理器启动 MCP 子进程并注册其工具；环境变量值不会从后端回传。</Dialog.Description>
            </div>
            <Dialog.Close asChild disabled={busy}>
              <button className="grid h-7 w-7 place-items-center rounded-md hover:bg-[var(--surface-inset)] disabled:opacity-40" aria-label="关闭"><X size={15} /></button>
            </Dialog.Close>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            {confirmSave ? (
              <div className="space-y-3">
                <div className="rounded-[var(--radius-sm)] border px-3 py-3 text-[12px]" style={{ borderColor: "var(--warn)", background: "var(--warn-tint)", color: "var(--fg)" }}>
                  <p className="font-semibold">确认执行以下 MCP 配置</p>
                  <p className="mt-1 text-[11px]" style={{ color: "var(--fg-muted)" }}>保存后，后端会{editing ? "卸载当前连接并按新配置重新启动" : draft.enabled ? "立即启动" : "保存但暂不启动"}该子进程。</p>
                </div>
                <Field label="完整命令">
                  <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-[var(--radius-sm)] border px-3 py-2 font-mono text-[12px]" style={controlStyle}>{commandPreview}</pre>
                </Field>
                <Field label="环境变量键（值已隐藏）">
                  <div className="rounded-[var(--radius-sm)] border px-3 py-2 font-mono text-[11px]" style={controlStyle}>{envKeys.length ? envKeys.join(", ") : "无"}</div>
                </Field>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Server 名称" hint={editing ? "已创建的名称不可修改。" : "也会进入 mcp__<server>__<tool> 工具命名空间。"}>
                    <input className={controlClass} style={controlStyle} value={draft.name} disabled={editing} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="filesystem" />
                  </Field>
                  <Field label="启动命令" hint="由后端主机直接启动，请填写可信的可执行文件。">
                    <input className={controlClass} style={controlStyle} value={draft.command} onChange={(event) => setDraft({ ...draft, command: event.target.value })} placeholder="npx" />
                  </Field>
                </div>
                <Field label="参数" hint="每行一个参数；包含空格的单个参数也保持一整行。">
                  <textarea className="h-28 w-full resize-y rounded-[var(--radius-sm)] border px-2.5 py-2 font-mono text-[12px] outline-none" style={controlStyle} value={draft.args} onChange={(event) => setDraft({ ...draft, args: event.target.value })} placeholder={"-y\n@modelcontextprotocol/server-filesystem\n/workspace"} />
                </Field>
                {editing && (
                  <Toggle checked={draft.replaceEnv} label="替换环境变量" hint={draft.replaceEnv ? "保存时用下方内容整体替换；留空表示清除。" : `保留后端现有值：${current?.env_keys.join(", ") || "无"}`} onChange={(checked) => setDraft({ ...draft, replaceEnv: checked })} />
                )}
                {draft.replaceEnv && (
                  <Field label="环境变量" hint="每行 KEY=value。值只会提交给后端，不会在后续读取时返回。">
                    <textarea className="h-28 w-full resize-y rounded-[var(--radius-sm)] border px-2.5 py-2 font-mono text-[12px] outline-none" style={controlStyle} value={draft.env} onChange={(event) => setDraft({ ...draft, env: event.target.value })} placeholder="API_TOKEN=..." />
                  </Field>
                )}
                <Toggle checked={draft.enabled} label="启用 Server" hint="启用时保存后立即连接并注册工具；关闭时仅保留配置。" onChange={(checked) => setDraft({ ...draft, enabled: checked })} />

                {editing && (
                  <div className="rounded-[var(--radius-sm)] border px-3 py-2" style={{ borderColor: "var(--border)", background: "var(--surface-inset)" }}>
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-[11px]">
                        <span style={{ color: "var(--fg-muted)" }}>状态：</span>
                        <span style={{ color: current?.status === "error" ? "var(--danger)" : "var(--fg)" }}>{current?.status ?? "读取中"}</span>
                        <span className="ml-3" style={{ color: "var(--fg-muted)" }}>工具：{current?.tool_count ?? 0}</span>
                      </div>
                      <Button size="xs" variant="secondary" disabled={busy} onClick={() => void testServer()}><FlaskConical size={12} />{test.isPending ? "测试中…" : "测试连接"}</Button>
                    </div>
                    {current?.error && <p className="mt-2 break-all text-[10px]" style={{ color: "var(--danger)" }}>{current.error}</p>}
                    {current?.tools && current.tools.length > 0 && <p className="mt-2 break-all font-mono text-[10px]" style={{ color: "var(--fg-subtle)" }}>{current.tools.map((tool) => tool.remote_name).join(", ")}</p>}
                    {test.data && <p className="mt-2 break-all text-[10px]" style={{ color: test.data.ok ? "var(--ok)" : "var(--danger)" }}>{test.data.ok ? `测试成功：发现 ${test.data.tools.length} 个工具${test.data.tools.length ? `（${test.data.tools.join(", ")}）` : ""}` : `测试失败：${test.data.error ?? "未知错误"}`}</p>}
                  </div>
                )}
              </div>
            )}

            {error && (
              <div className="mt-3 rounded-[var(--radius-sm)] border px-3 py-2 text-[11px]" style={{ borderColor: "var(--danger)", background: "var(--danger-tint)", color: "var(--danger)" }} role="alert">{error}</div>
            )}
          </div>

          <div className="flex items-center justify-between border-t px-5 py-3" style={{ borderColor: "var(--border)" }}>
            <div>
              {editing && !confirmSave && (
                <Button size="sm" variant={confirmDelete ? "danger" : "dangerGhost"} disabled={busy} onClick={() => void deleteServer()} onBlur={() => setConfirmDelete(false)}>
                  <Trash2 size={14} />{remove.isPending ? "删除中…" : confirmDelete ? "确认删除并停止" : "删除 Server"}
                </Button>
              )}
            </div>
            <div className="flex gap-2">
              {confirmSave ? (
                <>
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => setConfirmSave(false)}>返回修改</Button>
                  <Button size="sm" disabled={busy} onClick={() => void save()}><Save size={14} />{create.isPending || update.isPending ? "执行中…" : editing ? "确认并应用" : "确认并创建"}</Button>
                </>
              ) : (
                <>
                  <Button size="sm" variant="ghost" disabled={busy} onClick={onClose}>取消</Button>
                  <Button size="sm" disabled={busy} onClick={requestSave}><Save size={14} />继续确认</Button>
                </>
              )}
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function parseEnvSafely(value: string): Record<string, string> {
  try {
    return parseEnv(value);
  } catch {
    return {};
  }
}
