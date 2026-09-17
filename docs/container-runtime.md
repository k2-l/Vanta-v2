# Agent 容器运行时

Agent/Skill 文件协议不负责绑定容器。容器选择属于编排运行时：模型声明逻辑需求，
`RuntimeResolver` 根据管理员配置的 Container Profile 选择、探测并租用真实容器。

## 配置 Profile

先通过 `/v1/containers` 创建并启动容器，再写入 Profile：

容器必须有长期运行的镜像 CMD，或在创建请求中提供类似 `command: ["sleep", "infinity"]`；
仅设置 TTY 不会让一个已退出的镜像保持运行。禁网 runtime 创建时使用 `network_mode: "none"`。

```json
PUT /v1/containers/{container-record-id}/profile
{
  "capabilities": ["jdk17", "semgrep"],
  "purpose": "java-audit",
  "workspace_mode": "read-only",
  "network_policy": "none",
  "default_workdir": "/workspace",
  "agent_allowlist": ["java-auditor"],
  "max_concurrency": 1,
  "agent_ready": true
}
```

`agent_ready=true` 是显式接入开关。保存前后端会验证容器正在运行，并确认 `sh`、
`cat`、`tee`、`grep`、`find` 和工作目录满足公共工具契约。声明 `network_policy=none`
时，真实 Podman network mode 也必须是 `none`。声明 `network_policy=internet` 时，容器
必须使用非 `none` 网络，并且后端会从容器内部向固定的 `https://example.com/` 发起 HTTPS
探针，验证 DNS、TLS 和实际出网均可用；只配置 bridge 但无法访问互联网不会通过接入。

`agent_allowlist` 为空表示不允许任何 Agent 自动选择；`["*"]` 表示允许全部 Agent。

## Agent 自动选择

`Agent` 工具的可选 `runtime_requirements` 触发自动选择：

```json
{
  "name": "java-auditor",
  "task": "审计 Spring 项目",
  "runtime_requirements": {
    "capabilities": ["jdk17", "semgrep"],
    "network": "none",
    "workspace": "read-only"
  }
}
```

- 不确定管理员使用的 capability 标签时，先调用只读 `runtime_catalog` 工具；模型只能看到
  逻辑能力和策略，看不到 Podman ID、环境变量或宿主路径。
- 省略 `runtime_requirements`：保持原行为，子 Agent 继承父执行环境。
- 提供该对象（包括空对象）：Resolver 必须选择容器；没有匹配项时失败，不回退本机。
- 每个子 Agent invocation 独立选择和租用，因而同轮并行任务可以进入不同容器。
- Profile 保持接入时，如果长期容器异常退出，Resolver 会在下次选中时自动启动并重新执行
  readiness；任务完成只释放并发租约，不停止容器，避免反复支付冷启动成本。
- 管理端显式停止容器会先关闭自动接入，因此不会被 Agent 立即重新拉起；重新接入需要管理员
  启动容器并再次启用 Profile。
- 租约存在期间，管理 API 拒绝停止、删除容器、修改或删除 Profile；GUI 会显示当前
  `active_leases / max_concurrency`。
- 主动扫描器在普通 Agent 容器中仍要求有效 engagement，并被路由到受控 scope 沙箱；
  Container Profile 的网络策略因此只接受 `none` 和 `internet`，不会把普通容器冒充授权沙箱。
- 创建联网容器时选择 `network_mode=bridge`，再把 Profile 的 `network_policy` 设置为
  `internet`。代理通过 `runtime_requirements.network="internet"` 只会匹配通过出网探针的容器。
