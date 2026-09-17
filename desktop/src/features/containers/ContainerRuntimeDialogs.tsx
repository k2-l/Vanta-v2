import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useState, type ReactNode } from "react";
import { Activity, Play, Plus, Save, Square, Trash2, X } from "lucide-react";
import { Button } from "@/components/Button";
import { StatusBadge } from "@/components/desktop";
import { toClientError } from "@/contracts/errors";
import type {
  ContainerProfileInput,
  ContainerProfileWire,
  ContainerWire,
  CreateContainerInput,
} from "@/contracts/containers";
import {
  useContainerLifecycle,
  useContainerProfile,
  useContainerReadiness,
  useCreateContainer,
  useDeleteContainerProfile,
  useSaveContainerProfile,
} from "./useContainerRuntime";

const controlClass =
  "h-8 w-full rounded-[var(--radius-sm)] border px-2.5 text-[12px] outline-none focus:border-[var(--accent-line)] disabled:opacity-50";

function Control({ children, label, hint }: { children: ReactNode; label: string; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-medium" style={{ color: "var(--fg-muted)" }}>
        {label}
      </span>
      {children}
      {hint && (
        <span className="mt-1 block text-[10px] leading-relaxed" style={{ color: "var(--fg-subtle)" }}>
          {hint}
        </span>
      )}
    </label>
  );
}

function DialogFrame({ title, description, children, onClose }: {
  title: string;
  description: string;
  children: ReactNode;
  onClose: () => void;
}) {
  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-[2px]" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 flex max-h-[88vh] w-[min(720px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col rounded-[var(--radius-lg)] border shadow-2xl outline-none"
          style={{ background: "var(--surface-overlay)", borderColor: "var(--border)" }}
        >
          <div className="flex items-start gap-3 border-b px-5 py-4" style={{ borderColor: "var(--border)" }}>
            <div className="min-w-0 flex-1">
              <Dialog.Title className="text-[15px] font-semibold" style={{ color: "var(--fg)" }}>
                {title}
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-[11px]" style={{ color: "var(--fg-muted)" }}>
                {description}
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button className="grid h-7 w-7 place-items-center rounded-md hover:bg-[var(--surface-inset)]" aria-label="关闭">
                <X size={15} />
              </button>
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Message({ text, error = false }: { text?: string; error?: boolean }) {
  if (!text) return null;
  return (
    <div
      className="rounded-[var(--radius-sm)] border px-3 py-2 text-[11px]"
      style={{
        borderColor: error ? "var(--danger)" : "var(--ok)",
        background: error ? "var(--danger-tint)" : "var(--ok-tint)",
        color: error ? "var(--danger)" : "var(--ok)",
      }}
      role="status"
    >
      {text}
    </div>
  );
}

function lines(value: string): string[] {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

export function CreateContainerDialog({ onClose, onCreated }: {
  onClose: () => void;
  onCreated: (container: ContainerWire) => void;
}) {
  const create = useCreateContainer();
  const [name, setName] = useState("");
  const [image, setImage] = useState("");
  const [command, setCommand] = useState("sleep\ninfinity");
  const [ports, setPorts] = useState("");
  const [envVars, setEnvVars] = useState("");
  const [networkMode, setNetworkMode] = useState<"bridge" | "none">("none");
  const [workingDir, setWorkingDir] = useState("");
  const [error, setError] = useState<string>();

  const submit = async () => {
    if (!name.trim() || !image.trim()) {
      setError("容器名称和镜像不能为空");
      return;
    }
    if (workingDir.trim() && !workingDir.trim().startsWith("/")) {
      setError("工作目录必须是容器内绝对路径");
      return;
    }
    setError(undefined);
    const input: CreateContainerInput = {
      name: name.trim(),
      image: image.trim(),
      ports: lines(ports),
      env_vars: lines(envVars),
      command: lines(command).length ? lines(command) : null,
      network_mode: networkMode,
      working_dir: workingDir.trim(),
    };
    try {
      const result = await create.mutateAsync(input);
      onCreated(result);
    } catch (caught) {
      setError(toClientError(caught).message);
    }
  };

  return (
    <DialogFrame
      title="创建 Agent 容器"
      description="创建长期运行的 Podman 容器；创建后进入管理页启动并配置 Agent Profile。"
      onClose={onClose}
    >
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <div className="grid grid-cols-2 gap-3">
          <Control label="容器名称">
            <input className={controlClass} style={controlStyle} value={name} onChange={(event) => setName(event.target.value)} placeholder="java-audit-runtime" />
          </Control>
          <Control label="镜像">
            <input className={controlClass} style={controlStyle} value={image} onChange={(event) => setImage(event.target.value)} placeholder="registry/image:tag" />
          </Control>
          <Control label="网络模式">
            <select className={controlClass} style={controlStyle} value={networkMode} onChange={(event) => setNetworkMode(event.target.value as "bridge" | "none")}>
              <option value="none">none（禁网，推荐）</option>
              <option value="bridge">bridge（可联网）</option>
            </select>
          </Control>
          <Control label="工作目录" hint="可留空；必须是容器内绝对路径。">
            <input className={controlClass} style={controlStyle} value={workingDir} onChange={(event) => setWorkingDir(event.target.value)} placeholder="/workspace" />
          </Control>
        </div>
        <div className="mt-3 grid grid-cols-3 gap-3">
          <Control label="长期运行命令" hint="每行一个 argv；默认相当于 sleep infinity。">
            <textarea className="h-28 w-full resize-none rounded-[var(--radius-sm)] border px-2.5 py-2 font-mono text-[11px] outline-none" style={controlStyle} value={command} onChange={(event) => setCommand(event.target.value)} />
          </Control>
          <Control label="端口映射" hint="每行一个，例如 127.0.0.1:8080:8080。">
            <textarea className="h-28 w-full resize-none rounded-[var(--radius-sm)] border px-2.5 py-2 font-mono text-[11px] outline-none" style={controlStyle} value={ports} onChange={(event) => setPorts(event.target.value)} />
          </Control>
          <Control label="环境变量" hint="每行一个 KEY=value；不要放长期密钥。">
            <textarea className="h-28 w-full resize-none rounded-[var(--radius-sm)] border px-2.5 py-2 font-mono text-[11px] outline-none" style={controlStyle} value={envVars} onChange={(event) => setEnvVars(event.target.value)} />
          </Control>
        </div>
        <div className="mt-4">
          <Message text={error} error />
        </div>
      </div>
      <div className="flex justify-end gap-2 border-t px-5 py-3" style={{ borderColor: "var(--border)" }}>
        <Button size="sm" variant="ghost" disabled={create.isPending} onClick={onClose}>取消</Button>
        <Button size="sm" disabled={create.isPending} onClick={() => void submit()}>
          <Plus size={14} />
          {create.isPending ? "创建中…" : "创建容器"}
        </Button>
      </div>
    </DialogFrame>
  );
}

type ProfileDraft = {
  capabilities: string;
  purpose: string;
  workspaceMode: ContainerProfileInput["workspace_mode"];
  networkPolicy: ContainerProfileInput["network_policy"];
  defaultWorkdir: string;
  agentAllowlist: string;
  maxConcurrency: string;
  agentReady: boolean;
};

const EMPTY_PROFILE: ProfileDraft = {
  capabilities: "",
  purpose: "generic",
  workspaceMode: "none",
  networkPolicy: "none",
  defaultWorkdir: "",
  agentAllowlist: "",
  maxConcurrency: "1",
  agentReady: false,
};

function draftFromProfile(profile: ContainerProfileWire | null): ProfileDraft {
  if (!profile) return EMPTY_PROFILE;
  return {
    capabilities: profile.capabilities.join(", "),
    purpose: profile.purpose,
    workspaceMode: profile.workspace_mode,
    networkPolicy: profile.network_policy,
    defaultWorkdir: profile.default_workdir,
    agentAllowlist: profile.agent_allowlist.join(", "),
    maxConcurrency: String(profile.max_concurrency),
    agentReady: profile.agent_ready,
  };
}

function tags(value: string): string[] {
  return Array.from(new Set(value.split(/[,\n]/).map((item) => item.trim().toLowerCase()).filter(Boolean)));
}

export function ManageContainerDialog({ container, onClose }: { container: ContainerWire; onClose: () => void }) {
  const profile = useContainerProfile(container.id);
  const readiness = useContainerReadiness(container.id);
  const lifecycle = useContainerLifecycle();
  const saveProfile = useSaveContainerProfile();
  const deleteProfile = useDeleteContainerProfile();
  const [draft, setDraft] = useState<ProfileDraft>(EMPTY_PROFILE);
  const [message, setMessage] = useState<{ text: string; error?: boolean }>();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmDetach, setConfirmDetach] = useState(false);
  const [liveStatus, setLiveStatus] = useState(container.status ?? "unknown");

  useEffect(() => {
    if (profile.isSuccess) setDraft(draftFromProfile(profile.data));
  }, [profile.data, profile.isSuccess]);

  useEffect(() => setLiveStatus(container.status ?? "unknown"), [container.status]);

  const running = liveStatus.toLowerCase() === "running";
  const managed = container.managed !== false;
  const busy = lifecycle.isPending || saveProfile.isPending || deleteProfile.isPending;

  const act = async (action: "start" | "stop" | "delete") => {
    setMessage(undefined);
    try {
      const result = await lifecycle.mutateAsync({ containerId: container.id, action });
      if (action === "delete") {
        onClose();
      } else {
        if (result?.status) setLiveStatus(result.status);
        setMessage({ text: action === "start" ? "容器已启动" : "容器已停止，Agent 自动接入已关闭" });
      }
    } catch (caught) {
      setMessage({ text: toClientError(caught).message, error: true });
    }
  };

  const save = async () => {
    const maxConcurrency = Number(draft.maxConcurrency);
    if (!Number.isInteger(maxConcurrency) || maxConcurrency < 1 || maxConcurrency > 64) {
      setMessage({ text: "最大并发必须是 1–64 的整数", error: true });
      return;
    }
    if (draft.defaultWorkdir && !draft.defaultWorkdir.startsWith("/")) {
      setMessage({ text: "默认工作目录必须是容器内绝对路径", error: true });
      return;
    }
    if (draft.agentReady && !running) {
      setMessage({ text: "请先启动容器，再开启 Agent 自动接入", error: true });
      return;
    }
    const input: ContainerProfileInput = {
      capabilities: tags(draft.capabilities),
      purpose: draft.purpose.trim() || "generic",
      workspace_mode: draft.workspaceMode,
      network_policy: draft.networkPolicy,
      default_workdir: draft.defaultWorkdir.trim(),
      agent_allowlist: tags(draft.agentAllowlist),
      max_concurrency: maxConcurrency,
      agent_ready: draft.agentReady,
    };
    setMessage(undefined);
    try {
      await saveProfile.mutateAsync({ containerId: container.id, input });
      setMessage({ text: input.agent_ready ? "Profile 已保存并通过 readiness 校验" : "Profile 已保存，当前未接入 Agent 调度" });
    } catch (caught) {
      const error = toClientError(caught);
      setMessage({
        text: draft.agentReady && error.kind === "conflict"
          ? `Agent 接入校验未通过：${error.message}。可以先关闭“允许 Agent 自动选择”保存 Profile。`
          : `Profile 保存失败：${error.message}`,
        error: true,
      });
    }
  };

  const detach = async () => {
    if (!confirmDetach) {
      setConfirmDetach(true);
      return;
    }
    try {
      await deleteProfile.mutateAsync(container.id);
      setConfirmDetach(false);
      setMessage({ text: "Profile 已删除，容器不会再被 Agent 自动选择" });
    } catch (caught) {
      setMessage({ text: toClientError(caught).message, error: true });
    }
  };

  const checkReadiness = async () => {
    const result = await readiness.refetch();
    if (result.error) setMessage({ text: toClientError(result.error).message, error: true });
  };

  return (
    <DialogFrame
      title={container.name}
      description={`${container.image || "未知镜像"} · ${managed ? "Vanta 管理" : "外部容器（只读）"}`}
      onClose={onClose}
    >
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius)] border p-3" style={{ borderColor: "var(--border)", background: "var(--surface-inset)" }}>
          <div className="flex items-center gap-2">
            <StatusBadge tone={running ? "running" : "warn"}>{running ? "运行中" : `已停止 · ${liveStatus}`}</StatusBadge>
            <span className="font-mono text-[10px]" style={{ color: "var(--fg-subtle)" }}>{container.id}</span>
          </div>
          {managed && (
            <div className="flex items-center gap-2">
              {running ? (
                <Button size="xs" variant="secondary" disabled={busy} onClick={() => void act("stop")}><Square size={12} />停止</Button>
              ) : (
                <Button size="xs" variant="secondary" disabled={busy} onClick={() => void act("start")}><Play size={12} />启动</Button>
              )}
              <Button size="xs" variant={confirmDelete ? "danger" : "dangerGhost"} disabled={busy} onClick={() => confirmDelete ? void act("delete") : setConfirmDelete(true)} onBlur={() => setConfirmDelete(false)}>
                <Trash2 size={12} />{confirmDelete ? "确认删除" : "删除"}
              </Button>
            </div>
          )}
        </div>

        <div className="mt-3"><Message text={message?.text} error={message?.error} /></div>

        {!managed ? (
          <p className="mt-4 text-[12px]" style={{ color: "var(--fg-muted)" }}>该容器不是由 Vanta 创建，后端仅允许查看，不开放生命周期和 Agent Profile 操作。</p>
        ) : profile.isLoading ? (
          <p className="mt-4 text-[12px]" style={{ color: "var(--fg-muted)" }}>正在加载 Agent Profile…</p>
        ) : profile.isError ? (
          <Message text={toClientError(profile.error).message} error />
        ) : (
          <>
            <div className="mt-5 flex items-center justify-between">
              <div>
                <h3 className="text-[13px] font-semibold" style={{ color: "var(--fg)" }}>Agent Runtime Profile</h3>
                <p className="mt-0.5 text-[10px]" style={{ color: "var(--fg-subtle)" }}>能力标签用于任务匹配；开启接入时后端会执行真实容器探针。</p>
              </div>
              {profile.data && <StatusBadge tone={profile.data.agent_ready ? "ok" : "neutral"}>{profile.data.agent_ready ? profile.data.health_status : "未接入"}</StatusBadge>}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <Control label="能力标签" hint="逗号分隔，如 jdk17, semgrep。">
                <input className={controlClass} style={controlStyle} value={draft.capabilities} onChange={(event) => setDraft({ ...draft, capabilities: event.target.value })} />
              </Control>
              <Control label="用途">
                <input className={controlClass} style={controlStyle} value={draft.purpose} onChange={(event) => setDraft({ ...draft, purpose: event.target.value })} />
              </Control>
              <Control label="网络策略">
                <select className={controlClass} style={controlStyle} value={draft.networkPolicy} onChange={(event) => setDraft({ ...draft, networkPolicy: event.target.value as ProfileDraft["networkPolicy"] })}>
                  <option value="none">none（容器实际必须禁网）</option>
                  <option value="internet">internet（容器实际必须联网）</option>
                </select>
              </Control>
              <Control label="工作区权限">
                <select className={controlClass} style={controlStyle} value={draft.workspaceMode} onChange={(event) => setDraft({ ...draft, workspaceMode: event.target.value as ProfileDraft["workspaceMode"] })}>
                  <option value="none">none</option>
                  <option value="read-only">read-only</option>
                  <option value="read-write">read-write</option>
                </select>
              </Control>
              <Control label="默认工作目录">
                <input className={controlClass} style={controlStyle} value={draft.defaultWorkdir} onChange={(event) => setDraft({ ...draft, defaultWorkdir: event.target.value })} placeholder="/workspace" />
              </Control>
              <Control label="最大并发">
                <input className={controlClass} style={controlStyle} type="number" min={1} max={64} value={draft.maxConcurrency} onChange={(event) => setDraft({ ...draft, maxConcurrency: event.target.value })} />
              </Control>
              <div className="col-span-2">
                <Control label="允许的 Agent" hint='逗号分隔；空值表示全部拒绝，"*" 表示全部允许。'>
                  <input className={controlClass} style={controlStyle} value={draft.agentAllowlist} onChange={(event) => setDraft({ ...draft, agentAllowlist: event.target.value })} placeholder="java-auditor, audit-analyst" />
                </Control>
              </div>
            </div>
            <label className="mt-4 flex cursor-pointer items-center justify-between rounded-[var(--radius)] border px-3 py-2.5" style={{ borderColor: draft.agentReady ? "var(--accent)" : "var(--border)", background: draft.agentReady ? "var(--accent-tint)" : "var(--surface-inset)" }}>
              <span>
                <span className="block text-[12px] font-medium" style={{ color: "var(--fg)" }}>允许 Agent 自动选择</span>
                <span className="block text-[10px]" style={{ color: "var(--fg-subtle)" }}>保存时立即验证运行状态、网络策略和公共命令。</span>
              </span>
              <input type="checkbox" checked={draft.agentReady} onChange={(event) => setDraft({ ...draft, agentReady: event.target.checked })} />
            </label>

            {readiness.data && (
              <div className="mt-3"><Message text={readiness.data.reason} error={!readiness.data.ready} /></div>
            )}
            <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
              <div className="flex gap-2">
                <Button size="xs" variant="secondary" disabled={!running || readiness.isFetching} onClick={() => void checkReadiness()}>
                  <Activity size={12} />{readiness.isFetching ? "检查中…" : "检查 Readiness"}
                </Button>
                {profile.data && (
                  <Button size="xs" variant={confirmDetach ? "danger" : "dangerGhost"} disabled={busy} onClick={() => void detach()} onBlur={() => setConfirmDetach(false)}>
                    {confirmDetach ? "确认取消接入" : "删除 Profile"}
                  </Button>
                )}
              </div>
              <Button size="sm" disabled={busy} onClick={() => void save()}>
                <Save size={14} />{saveProfile.isPending ? "保存并检查…" : "保存 Profile"}
              </Button>
            </div>
          </>
        )}
      </div>
    </DialogFrame>
  );
}

const controlStyle = {
  background: "var(--surface-inset)",
  borderColor: "var(--border)",
  color: "var(--fg)",
};
