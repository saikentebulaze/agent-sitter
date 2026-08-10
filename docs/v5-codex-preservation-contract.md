# V5-A Codex 行为保真契约

V5-A 可以根本性重构内部结构，但不得静默改变已经试用有效的 Codex 行为。

## 字符级不变量

以下源资产受冻结 blob/hash 测试保护：

- `adapters/default/codex/config.toml`；
- 六个 `adapters/default/codex/agents/*.toml`；
- 生成的 `AGENTS.md`；
- `.codex/config.toml` 与 `.codex/agents/*.toml` marker；
- `.agents/skills/*/SKILL.md` wrapper。

任何 Prompt、description、model、reasoning effort、sandbox 或指令顺序变化必须作为独立优化任务处理，不能夹带在 Provider 重构中。

## 运行时不变量

Native subagent 必须继续证明：

- 唯一 `spawn_agent` 调用；
- `fork_turns: none`；
- child/parent thread 绑定；
- 指定 Agent、model、tier 和 reasoning effort；
- read-only sandbox；
- 项目 cwd；
- `codex-rollout-app-server-v1` + `verified-combined` evidence。

Managed isolated runtime 必须继续证明：

- 独立 App Server thread；
- `parentThreadId` 和 `forkedFromId` 为空；
- read-only sandbox 与 network disabled；
- 冻结 Agent profile hash；
- developer instructions 和请求参数 hash；
- `app-server-isolated-agent` execution type。

## 安装不变量

- 默认安装仍只启用 Codex；
- unmanaged 投影不得覆盖或删除；
- stale managed agent/skill 只能在验证所有权后删除；
- `.agent-work/` 与 `changes/` 不得被 reinstall 清理；
- linked worktree 使用 Git common root；
- post-swap 失败必须恢复旧 mirror；
- Provider 重构后投影内容与 V4.1 基线相同。

## 数据兼容

- 旧 Task 缺少 Provider 字段时解释为 Codex；
- 旧 delegation request 缺少 `runtime.provider` 时解释为 Codex；
- Codex attestation schema v2 保持有效；
- 原 CLI 和 Python import 路径保持兼容。

## 合并门槛

Draft PR 只有在以下条件全部满足后才可进入人工合并评估：

1. Ubuntu 和 Windows 全量 unittest 通过；
2. 字符级 Codex baseline 通过；
3. 安装冲突与回滚测试通过；
4. Provider compatibility identity tests 通过；
5. 真实 Sitter worktree 安装通过；
6. 真实 Codex 简单任务、Investigation、Scout、高风险 Change 和 Pivot 场景完成；
7. 未发现明显额外委派、步骤或 token 膨胀。
