# V5 Provider 架构重构说明

## 目标

V5 将 Harness 拆成稳定的 Governance Core 与可替换的 Agent Runtime Provider。Core 定义必须满足的治理不变量，Provider 负责把这些不变量映射到具体 Agent 的配置、权限、执行和证明机制。

V5-A 只正式支持 Codex。Claude Code、Kimi Code、OpenCode、Pi 等运行时不在本阶段实现。

## Core 边界

Core 包含：

- Task、Investigation、Production Change 工作图；
- Claim、Evidence、Experiment、Decision；
- RoleSpec、授权范围和角色化 Context Projection；
- Context Contract、不可变 attempt 和 stale detection；
- Delegation 结果提升规则；
- Provider-neutral RuntimeContract 与 RuntimeEvidence；
- Provider-owned ProjectionPlan、冲突检测和安装事务；
- Learning、Review、Knowledge Sync 和 Archive。

Core 不包含：

- 模型名称和 reasoning effort；
- `AGENTS.md`、`.codex` 或 Codex TOML；
- `spawn_agent`、rollout、App Server RPC；
- Codex trust、sandbox、thread ID 或 transcript 格式。

## Provider 边界

Codex Provider 当前负责：

- Agent profile 与模型映射；
- profile 静态校验；
- 项目信任管理；
- Codex 投影文本与 stale projection 识别；
- App Server client；
- native subagent attestation；
- managed isolated runtime；
- external `codex exec` fallback；
- Codex delegation runtime CLI。

旧的根目录模块继续存在，但只是兼容 re-export。测试必须证明旧 API 与 Provider 权威实现是同一个 Python 对象。

## 安装模型

每个 Provider 返回完整 `ProjectionPlan`。通用安装器：

1. 合并 Provider plans；
2. 在写入前拒绝跨 Provider 路径冲突；
3. 保护 unmanaged 文件；
4. staging Harness mirror；
5. 写入 Provider 投影；
6. 记录 projection owner 和 hash；
7. 更新 Git exclude；
8. 失败时恢复 mirror、投影和 exclude。

当前 registry 只注册 `codex`。不存在未实现 Provider 的空壳注册。

## 兼容策略

- 无 Provider 元数据的旧 Task 和 request 默认 Codex；
- 新 Task 写入 `execution.orchestrator_provider: codex`；
- 现有 Codex attestation schema v2 不迁移；
- 现有安装命令和 CLI 路径不变；
- Codex TOML、Prompt 和 Skill wrapper 受字符级基线保护；
- V5-A 不实现跨 Provider Task 交接。

## 后续 Provider 接入原则

新 Provider 必须实现真实配置、静态校验、投影计划、角色映射和运行时证明，不允许只注册名称。只有多个 Provider 已证明存在共同语义时，机制才允许继续提升到 Core；单一运行时特有能力留在 Provider 内。
