import * as Dialog from "@radix-ui/react-dialog";
import { useState, type ReactNode } from "react";
import { Bot, Save, Trash2, X } from "lucide-react";
import { Button } from "@/components/Button";
import type { AgentPatchInput, AgentWire } from "@/contracts/agents";
import { toClientError } from "@/contracts/errors";
import { useDeleteAgent, useRegisterAgent, useUpdateAgent } from "./useAgentManagement";

const controlClass =
  "h-8 w-full rounded-[var(--radius-sm)] border px-2.5 text-[12px] outline-none focus:border-[var(--accent-line)] disabled:opacity-50";
const controlStyle = {
  background: "var(--surface-inset)",
  borderColor: "var(--border)",
  color: "var(--fg)",
};

type AgentDraft = {
  name: string;
  description: string;
  content: string;
  model: string;
  provider: "" | "anthropic" | "openai";
  tools: string;
  enableCritic: boolean;
  disableModelInvocation: boolean;
  userInvocable: boolean;
};

const EMPTY_AGENT: AgentDraft = {
  name: "",
  description: "",
  content: "",
  model: "",
  provider: "",
  tools: "",
  enableCritic: false,
  disableModelInvocation: false,
  userInvocable: true,
};

function fromAgent(agent?: AgentWire): AgentDraft {
  if (!agent) return EMPTY_AGENT;
  return {
    name: agent.name,
    description: agent.description,
    content: agent.content,
    model: agent.model,
    provider: agent.provider ?? "",
    tools: agent.tools.join(", "),
    enableCritic: agent.enable_critic,
    disableModelInvocation: agent.disable_model_invocation,
    userInvocable: agent.user_invocable,
  };
}

function parseTools(value: string): string[] {
  return Array.from(new Set(value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean)));
}

/** JSON quoted strings/arrays are valid YAML scalars, avoiding hand-written escaping bugs. */
function renderAgentMarkdown(draft: AgentDraft): string {
  const frontmatter = [
    `name: ${JSON.stringify(draft.name.trim())}`,
    `description: ${JSON.stringify(draft.description.trim())}`,
  ];
  if (draft.model.trim()) frontmatter.push(`model: ${JSON.stringify(draft.model.trim())}`);
  if (draft.provider) frontmatter.push(`provider: ${JSON.stringify(draft.provider)}`);
  const tools = parseTools(draft.tools);
  if (tools.length) frontmatter.push(`tools: ${JSON.stringify(tools)}`);
  if (draft.enableCritic) frontmatter.push("enable_critic: true");
  if (draft.disableModelInvocation) frontmatter.push("disable-model-invocation: true");
  if (!draft.userInvocable) frontmatter.push("user-invocable: false");
  return `---\n${frontmatter.join("\n")}\n---\n\n${draft.content.trim()}\n`;
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

export function AgentDialog({ agent, onClose }: { agent?: AgentWire; onClose: () => void }) {
  const create = useRegisterAgent();
  const update = useUpdateAgent();
  const remove = useDeleteAgent();
  const [draft, setDraft] = useState<AgentDraft>(() => fromAgent(agent));
  const [error, setError] = useState<string>();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const editing = Boolean(agent);
  const busy = create.isPending || update.isPending || remove.isPending;

  const save = async () => {
    const name = draft.name.trim();
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(name)) {
      setError("名称仅允许字母、数字、点、下划线和连字符，长度 1–64");
      return;
    }
    if (!draft.description.trim()) {
      setError("Description 不能为空，它决定编排器何时选择该 Agent");
      return;
    }
    if (!draft.content.trim()) {
      setError("Agent system prompt 正文不能为空");
      return;
    }
    setError(undefined);
    try {
      if (agent) {
        const input: AgentPatchInput = {
          name,
          description: draft.description.trim(),
          content: draft.content.trim(),
          tools: parseTools(draft.tools),
          model: draft.model.trim(),
          provider: draft.provider || null,
          enable_critic: draft.enableCritic,
          disable_model_invocation: draft.disableModelInvocation,
          user_invocable: draft.userInvocable,
        };
        await update.mutateAsync({ agentId: agent.id, input });
      } else {
        await create.mutateAsync(renderAgentMarkdown({ ...draft, name }));
      }
      onClose();
    } catch (caught) {
      setError(toClientError(caught).message);
    }
  };

  const deleteAgent = async () => {
    if (!agent) return;
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    try {
      await remove.mutateAsync(agent.id);
      onClose();
    } catch (caught) {
      setError(toClientError(caught).message);
    }
  };

  return (
    <Dialog.Root open onOpenChange={(open) => !open && !busy && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-[2px]" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 flex max-h-[90vh] w-[min(780px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col rounded-[var(--radius-lg)] border shadow-2xl outline-none"
          style={{ background: "var(--surface-overlay)", borderColor: "var(--border)" }}
        >
          <div className="flex items-start gap-3 border-b px-5 py-4" style={{ borderColor: "var(--border)" }}>
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[var(--radius)]" style={{ background: "var(--accent-tint)", color: "var(--accent)" }}>
              <Bot size={17} />
            </span>
            <div className="min-w-0 flex-1">
              <Dialog.Title className="text-[15px] font-semibold" style={{ color: "var(--fg)" }}>{editing ? `编辑 ${agent?.name}` : "创建 Agent"}</Dialog.Title>
              <Dialog.Description className="mt-1 text-[11px]" style={{ color: "var(--fg-muted)" }}>保存到统一工作区协议 `workspace/agents/&lt;name&gt;/AGENT.md`，运行时无需重启即可重新加载。</Dialog.Description>
            </div>
            <Dialog.Close asChild disabled={busy}>
              <button className="grid h-7 w-7 place-items-center rounded-md hover:bg-[var(--surface-inset)] disabled:opacity-40" aria-label="关闭"><X size={15} /></button>
            </Dialog.Close>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Agent 名称" hint="改名会同步调整 Agent 目录名。">
                <input className={controlClass} style={controlStyle} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="java-auditor" />
              </Field>
              <Field label="模型" hint="留空则继承系统默认模型。">
                <input className={controlClass} style={controlStyle} value={draft.model} onChange={(event) => setDraft({ ...draft, model: event.target.value })} placeholder="claude-sonnet-4-6" />
              </Field>
              <div className="col-span-2">
                <Field label="Description" hint="L1 常驻描述，应明确什么时候把任务派给该 Agent。">
                  <textarea className="h-20 w-full resize-y rounded-[var(--radius-sm)] border px-2.5 py-2 text-[12px] outline-none" style={controlStyle} value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} />
                </Field>
              </div>
              <Field label="Provider">
                <select className={controlClass} style={controlStyle} value={draft.provider} onChange={(event) => setDraft({ ...draft, provider: event.target.value as AgentDraft["provider"] })}>
                  <option value="">自动推断</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="openai">OpenAI</option>
                </select>
              </Field>
              <Field label="工具白名单" hint="逗号或换行分隔；空表示继承默认工具集。">
                <input className={controlClass} style={controlStyle} value={draft.tools} onChange={(event) => setDraft({ ...draft, tools: event.target.value })} placeholder="Read, Grep, Glob, Bash, Skill" />
              </Field>
            </div>

            <div className="mt-3 grid grid-cols-3 gap-2">
              <Toggle checked={draft.enableCritic} label="Critic 质量门" hint="执行后增加结果质量评审" onChange={(checked) => setDraft({ ...draft, enableCritic: checked })} />
              <Toggle checked={!draft.disableModelInvocation} label="模型可自动选择" hint="进入编排器 L1 Agent 目录" onChange={(checked) => setDraft({ ...draft, disableModelInvocation: !checked })} />
              <Toggle checked={draft.userInvocable} label="用户可调用" hint="允许出现在用户调用入口" onChange={(checked) => setDraft({ ...draft, userInvocable: checked })} />
            </div>

            <div className="mt-3">
              <Field label="System Prompt 正文" hint="对应 AGENT.md frontmatter 后的 Markdown 正文。">
                <textarea className="min-h-64 w-full resize-y rounded-[var(--radius-sm)] border px-3 py-2.5 font-mono text-[12px] leading-relaxed outline-none" style={controlStyle} value={draft.content} onChange={(event) => setDraft({ ...draft, content: event.target.value })} placeholder="你是一名……" />
              </Field>
            </div>

            {error && (
              <div className="mt-3 rounded-[var(--radius-sm)] border px-3 py-2 text-[11px]" style={{ borderColor: "var(--danger)", background: "var(--danger-tint)", color: "var(--danger)" }} role="alert">{error}</div>
            )}
          </div>

          <div className="flex items-center justify-between border-t px-5 py-3" style={{ borderColor: "var(--border)" }}>
            <div>
              {editing && (
                <Button size="sm" variant={confirmDelete ? "danger" : "dangerGhost"} disabled={busy} onClick={() => void deleteAgent()} onBlur={() => setConfirmDelete(false)}>
                  <Trash2 size={14} />{remove.isPending ? "删除中…" : confirmDelete ? "确认删除 Agent" : "删除 Agent"}
                </Button>
              )}
            </div>
            <div className="flex gap-2">
              <Button size="sm" variant="ghost" disabled={busy} onClick={onClose}>取消</Button>
              <Button size="sm" disabled={busy} onClick={() => void save()}>
                <Save size={14} />{create.isPending || update.isPending ? "保存中…" : editing ? "保存修改" : "创建 Agent"}
              </Button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
