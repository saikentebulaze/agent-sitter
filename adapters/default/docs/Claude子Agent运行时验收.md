# Claude 子 Agent 运行时验收

V5-B 的 Claude Provider 必须分别验证 managed 与 native execution。配置文件、Agent 自述或最终答案正确均不足以证明受控执行。

## Settings ownership

`.claude/settings.local.json` 由 Claude Code 和用户所有。Harness 不创建、不覆盖、不删除该文件，也不把整份文件作为受管 projection。

Harness 的运行时控制位于安装 mirror：

```text
.harness/sitter/adapters/default/claude/governed-settings.json
```

managed CLI 与 native governed parent 均通过 `--settings` 显式加载该冻结文件。它负责父会话 Agent invocation Hook、SubagentStart/Stop、Auto Memory、background 和 fork 控制。

Agent frontmatter 只包含 child-scoped Hook：Pre/PostToolUse、Pre/PostCompact 和 WorktreeCreate。父 lifecycle Hook 不得注入 Agent frontmatter。

## Managed execution

Managed attestation schema v2 使用：

```text
method: claude-managed-agent
collector: claude-stream-hooks-transcript-v2
source: verified-claude-managed-v2
```

必须在模型执行前验证：

- executable path 和 SHA-256；
- Claude Code version；
- Windows command shim 是否唯一解析到真实 claude executable；
- frozen profile、model config、Agent、governed settings 和 Hook hashes。

运行后必须核验 stream/init、session、resolved model、reasoning effort、Read/Grep/Glob、strict empty MCP、cwd、lifecycle Hook 和 continuity events。

## Native execution

Native attestation schema v2 使用：

```text
method: claude-native-subagent
collector: claude-invocation-hooks-transcript-v2
source: verified-claude-native-v2
```

必须使用：

```powershell
python runtime\claude_native_runtime.py --project <root> prepare <task> <delegation>
python runtime\claude_native_runtime.py --project <root> launch <task> <delegation>
python runtime\claude_native_runtime.py --project <root> collect <task> <delegation>
```

`launch` 创建 fresh governed parent，并注入 attempt nonce。Claude Code 2.1.217 需要 parent CLI 注册 `Agent,Read,Grep,Glob` 才能把 child 的 Read/Grep/Glob 工具正确传播到 Agent；这不代表 parent 可以直接使用这些文件工具。

governed Hook 对没有 `agent_id` 的 native parent 只允许 `Agent`。parent 直接 Read/Grep/Glob 会在 `PreToolUse` 被拒绝；child 才允许受 per-attempt scope policy 约束的 Read/Grep/Glob。

Collector 必须将以下证据绑定成唯一链：

```text
frozen request
  -> native contract + attempt nonce
  -> parent PreToolUse(Agent): exact prompt/subagent_type/tool_use_id/model/foreground
  -> SubagentStart: agent_id/runtime role
  -> child transcript from SubagentStop.agent_transcript_path
  -> SubagentStop final message
  -> parent PostToolUse(Agent): same tool_use_id/agentId/completed/resolvedModel
```

`transcript_path` 是父会话 transcript，`agent_transcript_path` 是 child transcript，两者不得混用。出现错误 prompt、background、第二个 Agent、多个 cwd/model、非法工具、nested Agent、compact/worktree、final-message 不一致或 transcript 篡改时必须拒绝。

## Model resolution

默认只接受 native selector family/exact match。Claude-compatible proxy 必须在模型配置中显式冻结：

```yaml
resolution_mode: explicit-proxy
expected_resolved_model: deepseek-v4-flash
proxy_provider: deepseek
```

运行后读取用户 settings 来补充 proxy 证明不被接受。

## Filesystem scope

每次 delegation 从 frozen request 生成 `attempt-XX.scope-policy.json`。Read/Grep/Glob 的目标必须落在 allowed scope 内，exclude 优先于 include；Grep/Glob 必须显式提供 `path`。

Hook deny 的 `PreToolUse` 只有在同一 `tool_use_id` 没有对应 `PostToolUse` 时才构成有效机械拒绝证据。record 阶段重新核验 policy/request/event hashes。

## 验收判定

正式 runtime pass 必须记录完整 Hook、parent/child transcript、实际模型、工具调用、上下文来源、文件副作用和所有 provenance hashes。

必须区分：

- **Capability FAIL**：非法能力真实执行而 Harness 未阻止；
- **INCONCLUSIVE**：没有足够机械或真实 runtime 证据证明 enforcement；
- **N/A / NOT EXERCISED**：当前模型/runtime 没有触发目标 live branch，但同一机械 enforcement path 已有直接拒绝证据，目标 runtime 已证明加载同一 Hook/policy/collector，且 deterministic tests 已覆盖该拒绝路径。

模型主动拒绝发起非法调用，不能单独证明权限边界；也不能在已有等价机械 enforcement 证据时把 capability 降为 `INCONCLUSIVE`。
