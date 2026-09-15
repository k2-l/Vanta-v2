"""权限引擎（ADR-0003 P3 / T3.1）——纯逻辑，给定一次工具调用判定 allow / ask / deny。

采纳 Claude Code「跑任意命令 + 权限门」模型：模型可请求任意命令，由 harness 在执行前
按规则放行 / 询问 / 拒绝（替代旧的命令白名单沙箱）。

- 规则三态：`allow` / `ask` / `deny`，优先级 **deny > ask > allow**。
- 规则串：`ToolName` 或 `ToolName(pattern)`。Bash 的 pattern 按命令匹配：
  含通配（`*?[`，`:*` 归一为 `*`）走 fnmatch，否则按「程序名或整串」匹配。
- 复合命令（`a && b | c; d`）拆开逐段判定，取**最严**（任一 deny→deny，任一 ask→ask）。
- 权限模式：`default` / `acceptEdits`（自动放行文件写） / `plan`（只读，禁副作用） / `bypass`（全放行）。
- `env`（local/container）作为默认策略输入：容器内隔离即沙箱，未命中规则默认放行；
  host 上未命中且非只读则 ask。

本模块不做任何 IO、不改任何现有路径；接入执行路径与配置加载在 T3.2 完成。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fnmatch import fnmatch

Decision = str  # "allow" | "ask" | "deny"

# 只读工具：默认放行；plan 模式下也只允许这些
READ_ONLY_TOOLS: frozenset[str] = frozenset({
    "Read", "Grep", "Glob",
    "knowledge",
})

# acceptEdits 模式下自动放行的文件写工具
_EDIT_TOOLS: frozenset[str] = frozenset({"Write", "Edit"})

# 走命令解析的执行类工具
_BASH_TOOLS: frozenset[str] = frozenset({"Bash"})

# 复合命令分隔符：&& || | ; 及换行
_SPLIT_RE = re.compile(r"\s*(?:&&|\|\||[|;\n])\s*")

# 承接旧 SAFE_COMMANDS 的只读类命令（默认 allow）
_SAFE_BASH = [
    "ls", "cat", "head", "tail", "echo", "pwd", "whoami", "hostname", "date",
    "git", "rg", "grep", "find", "wc", "uname", "which", "env", "sort", "uniq",
    "diff", "tree", "stat", "file", "du", "df", "ps", "cut", "basename",
    "dirname", "realpath",
]
# 默认 ask：曾被旧白名单硬禁的命令（解释器/网络/包管理/提权/shell）+ 破坏性命令。
# 取向：T3.3 拆掉白名单后，曾被禁的命令改为"可执行但需审批"，而非静默放行。
_RISKY_BASH = [
    # 解释器
    "python", "python2", "python3", "node", "nodejs", "ruby", "perl", "php", "lua",
    # 网络
    "curl", "wget", "nc", "ncat", "netcat", "telnet", "ssh", "scp", "sftp", "rsync",
    # 提权 / shell
    "sudo", "su", "doas", "bash", "sh", "zsh", "dash", "fish",
    # 包管理 / 构建
    "pip", "pip2", "pip3", "npm", "npx", "yarn", "pnpm", "uv", "uvx", "cargo", "go",
    "apt", "apt-get", "dpkg", "yum", "dnf", "pacman", "brew",
    # 破坏性
    "rm", "rmdir", "mv", "dd", "kill", "pkill", "killall", "chmod", "chown", "chgrp",
    "mkfs", "shutdown", "reboot", "systemctl", "service", "mount", "umount",
]

# 主动扫描器名单：host 上默认 deny（fail-safe，不在 harness 进程内裸扫全网），须进
# per-engagement egress 锁定沙箱跑；容器内不受此限（env=="container" 放行 + nft 兜底 scope）。
_HOST_DENIED_TOOLS: frozenset[str] = frozenset({
    "nmap", "masscan", "zmap", "nuclei", "sqlmap", "gobuster", "ffuf", "dirb",
    "nikto", "wpscan", "hydra", "medusa", "whatweb", "wfuzz", "feroxbuster",
    "amass", "subfinder", "httpx", "naabu", "dnsx", "katana",
})


def _first_program(command: str) -> str:
    """取命令首个 token 的程序名（去路径），best-effort。"""
    toks = command.strip().split()
    return toks[0].rsplit("/", 1)[-1] if toks else ""


@dataclass
class PermissionRules:
    allow: list[str] = field(default_factory=list)
    ask: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)


DEFAULT_RULES = PermissionRules(
    allow=[f"Bash({c})" for c in _SAFE_BASH] + sorted(READ_ONLY_TOOLS),
    ask=[f"Bash({c})" for c in _RISKY_BASH] + ["Bash(sudo*)"],
    deny=["Bash(rm -rf /)", "Bash(rm -rf /*)", "Bash(:(){*)"],
)


def merge_rules(base: PermissionRules, allow=None, ask=None, deny=None) -> PermissionRules:
    """在 base 之上叠加配置规则（追加，不覆盖）。"""
    return PermissionRules(
        allow=[*base.allow, *(allow or [])],
        ask=[*base.ask, *(ask or [])],
        deny=[*base.deny, *(deny or [])],
    )


def _parse_rule(rule: str) -> tuple[str, str | None]:
    """`Bash(git*)` → ('Bash', 'git*')；`Read` → ('Read', None)。"""
    rule = rule.strip()
    if rule.endswith(")") and "(" in rule:
        tool, _, rest = rule.partition("(")
        return tool.strip(), rest[:-1].strip()
    return rule, None


def _match_bash(command: str, pattern: str) -> bool:
    if not command:
        return False
    pat = pattern.replace(":*", "*")
    if any(ch in pat for ch in "*?["):
        return fnmatch(command, pat)
    return command == pattern or command.split(maxsplit=1)[0] == pattern


def _match(tool_name: str, subject: str | None, rule_list: list[str]) -> bool:
    """subject：Bash 为单条子命令字符串；其它工具为 None（仅按工具名级规则匹配）。"""
    for rule in rule_list:
        rtool, rpat = _parse_rule(rule)
        if rtool != tool_name:
            continue
        if rpat is None:
            return True
        if subject is not None and _match_bash(subject, rpat):
            return True
    return False


def _subjects(tool_name: str, tool_input: dict) -> list[str | None]:
    if tool_name in _BASH_TOOLS:
        cmd = str(tool_input.get("command", "")).strip()
        parts = [p.strip() for p in _SPLIT_RE.split(cmd) if p.strip()]
        return parts or [""]  # type: ignore[list-item]
    return [None]


def _eval_subject(
    tool_name: str, subject: str | None, mode: str, env: str, engaged: bool, rules: PermissionRules
) -> Decision:
    if _match(tool_name, subject, rules.deny):
        return "deny"
    # plan：只读探索模式——仅放行 allow 规则命中或只读工具，其余一律拒绝（含 ask/未知）
    if mode == "plan":
        if _match(tool_name, subject, rules.allow) or tool_name in READ_ONLY_TOOLS:
            return "allow"
        return "deny"
    # 容器内隔离即沙箱：除 deny 外全放行（忽略 ask 规则）
    if env == "container":
        return "allow"
    # 安全扫描器：无 engagement 时 host 上 deny（fail-safe）；有 engagement 时放行——
    # Bash 工具会把它路由进该 engagement 的 egress 锁定沙箱（见 shell.py）。
    if tool_name in _BASH_TOOLS and _first_program(subject or "") in _HOST_DENIED_TOOLS:
        return "allow" if engaged else "deny"
    if mode == "acceptEdits" and tool_name in _EDIT_TOOLS:
        return "allow"
    if _match(tool_name, subject, rules.ask):
        return "ask"
    # host 默认放行（CC「跑任意命令」；危险命令由 ask/deny 规则显式拦截）
    return "allow"


def evaluate(
    tool_name: str,
    tool_input: dict,
    *,
    mode: str = "default",
    env: str = "local",
    engaged: bool = False,
    rules: PermissionRules | None = None,
) -> Decision:
    """判定一次工具调用：返回 'allow' / 'ask' / 'deny'。engaged=有活跃 engagement（扫描器放行→沙箱路由）。"""
    if mode == "bypass":
        return "allow"
    rules = rules or DEFAULT_RULES
    decisions = [
        _eval_subject(tool_name, s, mode, env, engaged, rules)
        for s in _subjects(tool_name, tool_input)
    ]
    if "deny" in decisions:
        return "deny"
    if "ask" in decisions:
        return "ask"
    return "allow"


def active_policy() -> tuple[str, PermissionRules]:
    """从 settings 读取当前权限模式与合并后的规则（默认规则 + 配置叠加）。"""
    from harness.infra.settings import get_settings

    s = get_settings()
    rules = merge_rules(
        DEFAULT_RULES,
        allow=getattr(s, "permission_allow", None),
        ask=getattr(s, "permission_ask", None),
        deny=getattr(s, "permission_deny", None),
    )
    return getattr(s, "permission_mode", "default"), rules
