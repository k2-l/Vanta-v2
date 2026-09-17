import * as Dialog from "@radix-ui/react-dialog";
import { useState, type ReactNode } from "react";
import { Save, Trash2, Wrench, X } from "lucide-react";
import { Button } from "@/components/Button";
import type { SkillPatchInput, SkillWire } from "@/contracts/skills";
import { toClientError } from "@/contracts/errors";
import { useDeleteSkill, useRegisterSkill, useUpdateSkill } from "./useSkillManagement";

const controlClass =
  "h-8 w-full rounded-[var(--radius-sm)] border px-2.5 text-[12px] outline-none focus:border-[var(--accent-line)] disabled:opacity-50";
const controlStyle = {
  background: "var(--surface-inset)",
  borderColor: "var(--border)",
  color: "var(--fg)",
};

type SkillDraft = {
  name: string;
  description: string;
  content: string;
  model: string;
  allowedTools: string;
  argumentHint: string;
  disableModelInvocation: boolean;
  userInvocable: boolean;
};

const EMPTY_SKILL: SkillDraft = {
  name: "",
  description: "",
  content: "",
  model: "",
  allowedTools: "",
  argumentHint: "",
  disableModelInvocation: false,
  userInvocable: true,
};

function fromSkill(skill?: SkillWire): SkillDraft {
  if (!skill) return EMPTY_SKILL;
  return {
    name: skill.name,
    description: skill.description,
    content: skill.content,
    model: skill.model,
    allowedTools: skill.allowed_tools.join(", "),
    argumentHint: skill.argument_hint,
    disableModelInvocation: skill.disable_model_invocation,
    userInvocable: skill.user_invocable,
  };
}

function parseTools(value: string): string[] {
  return Array.from(new Set(value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean)));
}

/** JSON 引号串/数组本身即合法 YAML 标量，避免手写转义出错。 */
function renderSkillMarkdown(draft: SkillDraft): string {
  const frontmatter = [
    `name: ${JSON.stringify(draft.name.trim())}`,
    `description: ${JSON.stringify(draft.description.trim())}`,
  ];
  if (draft.model.trim()) frontmatter.push(`model: ${JSON.stringify(draft.model.trim())}`);
  const tools = parseTools(draft.allowedTools);
  if (tools.length) frontmatter.push(`allowed-tools: ${JSON.stringify(tools)}`);
  if (draft.argumentHint.trim()) frontmatter.push(`argument-hint: ${JSON.stringify(draft.argumentHint.trim())}`);
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

export function SkillDialog({ skill, onClose }: { skill?: SkillWire; onClose: () => void }) {
  const create = useRegisterSkill();
  const update = useUpdateSkill();
  const remove = useDeleteSkill();
  const [draft, setDraft] = useState<SkillDraft>(() => fromSkill(skill));
  const [error, setError] = useState<string>();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const editing = Boolean(skill);
  const busy = create.isPending || update.isPending || remove.isPending;

  const save = async () => {
    const name = draft.name.trim();
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(name)) {
      setError("名称仅允许字母、数字、点、下划线和连字符，长度 1–64");
      return;
    }
    if (!draft.description.trim()) {
      setError("Description 不能为空，它决定模型/用户何时选择该 Skill");
      return;
    }
    if (!draft.content.trim()) {
      setError("Skill SOP 正文不能为空");
      return;
    }
    setError(undefined);
    try {
      if (skill) {
        const input: SkillPatchInput = {
          name,
          description: draft.description.trim(),
          content: draft.content.trim(),
          allowed_tools: parseTools(draft.allowedTools),
          model: draft.model.trim(),
          argument_hint: draft.argumentHint.trim(),
        };
        await update.mutateAsync({ skillId: skill.id, input });
      } else {
        await create.mutateAsync(renderSkillMarkdown({ ...draft, name }));
      }
      onClose();
    } catch (caught) {
      setError(toClientError(caught).message);
    }
  };

  const deleteSkill = async () => {
    if (!skill) return;
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    try {
      await remove.mutateAsync(skill.id);
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
              <Wrench size={17} />
            </span>
            <div className="min-w-0 flex-1">
              <Dialog.Title className="text-[15px] font-semibold" style={{ color: "var(--fg)" }}>{editing ? `编辑 ${skill?.name}` : "创建 Skill"}</Dialog.Title>
              <Dialog.Description className="mt-1 text-[11px]" style={{ color: "var(--fg-muted)" }}>保存到工作区 `skills/&lt;name&gt;/SKILL.md`，运行时无需重启即可重新加载。</Dialog.Description>
            </div>
            <Dialog.Close asChild disabled={busy}>
              <button className="grid h-7 w-7 place-items-center rounded-md hover:bg-[var(--surface-inset)] disabled:opacity-40" aria-label="关闭"><X size={15} /></button>
            </Dialog.Close>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Skill 名称" hint="改名会同步调整 Skill 目录名。">
                <input className={controlClass} style={controlStyle} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="java-audit" />
              </Field>
              <Field label="模型" hint="留空则继承系统默认模型。">
                <input className={controlClass} style={controlStyle} value={draft.model} onChange={(event) => setDraft({ ...draft, model: event.target.value })} placeholder="claude-sonnet-4-6" />
              </Field>
              <div className="col-span-2">
                <Field label="Description" hint="L1 常驻描述，应明确什么任务符合该 Skill 的用途。">
                  <textarea className="h-20 w-full resize-y rounded-[var(--radius-sm)] border px-2.5 py-2 text-[12px] outline-none" style={controlStyle} value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} />
                </Field>
              </div>
              <Field label="工具白名单" hint="逗号或换行分隔；空表示不预设工具限制。">
                <input className={controlClass} style={controlStyle} value={draft.allowedTools} onChange={(event) => setDraft({ ...draft, allowedTools: event.target.value })} placeholder="Read, Grep, Glob, Bash" />
              </Field>
              <Field label="调用参数说明" hint="argument-hint：说明加载该 Skill 时如何传参。">
                <input className={controlClass} style={controlStyle} value={draft.argumentHint} onChange={(event) => setDraft({ ...draft, argumentHint: event.target.value })} placeholder="<目标目录>" />
              </Field>
            </div>

            {!editing && (
              <div className="mt-3 grid grid-cols-2 gap-2">
                <Toggle checked={!draft.disableModelInvocation} label="模型可自动选择" hint="进入编排器 L1 Skill 清单" onChange={(checked) => setDraft({ ...draft, disableModelInvocation: !checked })} />
                <Toggle checked={draft.userInvocable} label="用户可调用" hint="允许出现在用户调用入口" onChange={(checked) => setDraft({ ...draft, userInvocable: checked })} />
              </div>
            )}

            <div className="mt-3">
              <Field label="SOP 正文" hint="对应 SKILL.md frontmatter 后的 Markdown 正文（标准操作流程 / 步骤）。">
                <textarea className="min-h-64 w-full resize-y rounded-[var(--radius-sm)] border px-3 py-2.5 font-mono text-[12px] leading-relaxed outline-none" style={controlStyle} value={draft.content} onChange={(event) => setDraft({ ...draft, content: event.target.value })} placeholder="## 用途&#10;……&#10;&#10;## 步骤&#10;1. ……" />
              </Field>
            </div>

            {error && (
              <div className="mt-3 rounded-[var(--radius-sm)] border px-3 py-2 text-[11px]" style={{ borderColor: "var(--danger)", background: "var(--danger-tint)", color: "var(--danger)" }} role="alert">{error}</div>
            )}
          </div>

          <div className="flex items-center justify-between border-t px-5 py-3" style={{ borderColor: "var(--border)" }}>
            <div>
              {editing && (
                <Button size="sm" variant={confirmDelete ? "danger" : "dangerGhost"} disabled={busy} onClick={() => void deleteSkill()} onBlur={() => setConfirmDelete(false)}>
                  <Trash2 size={14} />{remove.isPending ? "删除中…" : confirmDelete ? "确认删除 Skill" : "删除 Skill"}
                </Button>
              )}
            </div>
            <div className="flex gap-2">
              <Button size="sm" variant="ghost" disabled={busy} onClick={onClose}>取消</Button>
              <Button size="sm" disabled={busy} onClick={() => void save()}>
                <Save size={14} />{create.isPending || update.isPending ? "保存中…" : editing ? "保存修改" : "创建 Skill"}
              </Button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
