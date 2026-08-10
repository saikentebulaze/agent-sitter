# V5-A 本地 Codex 验收

## 1. 准备隔离 worktree

不要直接升级日常开发目录：

```powershell
git worktree add E:\code\Refactor\v5-harness-test <test-branch>
```

从 Harness PR 分支安装：

```powershell
powershell -ExecutionPolicy Bypass -File `
  E:\code\Harness\sitter\scripts\acceptance\codex-static-regression.ps1 `
  -ProjectRoot E:\code\Refactor\v5-harness-test `
  -TrustProject
```

关闭旧 Codex 会话，从目标 worktree 根目录启动新会话。

## 2. 运行时发现

确认：

- `AGENTS.md` 被加载；
- `$change-governor` 可调用；
- 六个 Sitter Agent 可发现；
- `self_check.py` 通过；
- manifest 显示 `enabled_providers: [codex]`；
- 所有 projection owner 均为 `codex`。

## 3. 固定行为场景

### A. 简单任务

选择一个低风险、局部且明确的任务。检查：

- 不因 V5 Provider 架构额外启动子 Agent；
- 不创建不必要的 Investigation/Change；
- 与 V4.1 相比步骤和上下文没有明显膨胀。

### B. 普通 Investigation

检查：

- 正确创建 Task 和 Investigation；
- 根因未稳定前不修改生产代码；
- Claim、Evidence、Experiment、Decision 引用闭环；
- 旧 Task 缺少 Provider 元数据仍可验证。

### C. Context Scout

先记录实际执行模式，再应用对应证明标准。两种模式均为合法路径，但不能混用验收条件。

#### C1. Native audited subagent

检查：

- `execution.method: native-subagent`；
- collector 为 `codex-rollout-app-server-v1`；
- role 为 `context_scout`；
- model/tier/effort 为 `gpt-5.6-luna / luna / medium`；
- sandbox 为 read-only；
- context inheritance 为 none；
- spawn call、parent thread 与 child thread 唯一绑定；
- attestation schema v2 和 `verified-combined` evidence 通过。

#### C2. Managed isolated agent

检查：

- `execution.method: app-server-isolated-agent`；
- collector 为 `codex-app-server-managed-v1`；
- role、model/tier/effort 与请求 profile 一致；
- sandbox 为 read-only，网络关闭；
- context inheritance 为 none；
- `parent_thread_id` 和 `forked_from_id` 均为空；
- child thread、profile hash、developer instructions hash、thread/turn request hash 完整；
- attestation schema v2 和 `verified-app-server-managed` evidence 通过。

Managed isolated agent 本来就没有 native spawn call。不得因为缺少 native spawn call 将合法 managed 运行判为失败，也不得用 managed 证据冒充 native spawn 审计。

### D. 高风险 Change 与设计决策检查点

先运行不会写入项目的合成 fixture：

```powershell
python <harness-root>\scripts\acceptance\high-risk-governance-fixture.py
```

它只在系统临时目录创建治理工件，并依次证明：

1. HIGH Change 在 `proposed` 阶段可以记录未解决的 material fork；
2. 进入 `approved` 或后续状态时，未解决的 `human_in_loop` 决策被阻断；
3. 决策已解决但 approval 未批准时仍被阻断；
4. 显式决策证据与 approval 均完成后才允许继续；
5. Task-level `human-checkpoint` 为 pending 时，Task 必须保持 `blocked`。

这里的 `Change.human_in_loop` 是常规高风险设计门，`Task.escalation.level: human-checkpoint` 是 stronger-model 仍无法收敛后的升级门。两者分别验收，不要求一次真实生产改动同时触发。

真实 Change 还需检查：

- material decision fork 被识别；
- 审批前不实现；
- verification、review、knowledge sync 和 archive 顺序正确；
- fixture 与验收过程不修改生产源码。

### E. Pivot 与升级

检查：

- Investigation 与 Change 双向 Pivot；
- repeated pivot 需要新增区分能力；
- stronger-model escalation 正常；
- Terra 审查为 inconclusive/blocked 后，才进入 Task-level human checkpoint；
- unresolved human checkpoint 阻止继续。

## 4. Legacy knowledge index

旧项目的 `knowledge/index.yaml` 可能仍使用 `kind`/`status`。这不是合法的新 schema，也不得静默接受。

先诊断：

```powershell
python runtime\knowledge_tool.py --project <root> diagnose
```

生成独立迁移候选，不覆盖源文件：

```powershell
python runtime\knowledge_tool.py --project <root> migration-plan `
  --output knowledge\index.v5-candidate.yaml `
  --evidence-status candidate `
  --architecture-status legacy
```

`kind` 只有在可无歧义映射为当前 `type` 时才自动转换；旧 `status` 不会被猜测拆分，必须通过命令行显式给出新的 evidence/architecture 状态。候选文件需人工审查后再替换源索引。

Change 尚未进入 knowledge sync/archive 时，旧索引只产生明确 warning，不遮蔽风险、审批和 Human-in-the-loop 门；进入 `syncing`、`ready-to-archive`、`archived`，或已有 knowledge candidate/review/promotion 时，索引错误继续硬阻断。

## 5. 结果记录

每个场景记录：

- Codex CLI 版本；
- Task/Investigation/Change 引用；
- 使用的 Agent、model、tier、effort；
- execution method、collector、runtime attestation 与 evidence 路径；
- 是否发生额外委派；
- 与 V4.1 的行为差异；
- 结论：pass / regression / needs-optimization。

不要以自然语言输出逐字一致作为通过条件；治理顺序、安全边界、角色路由和运行时证明必须一致。

## 6. 增量复验

首轮验收若已确认运行时发现、普通 Investigation、managed Context Scout 和 Pivot 基本路径，可只复验后续修正项：

1. 按 C2 标准重新判定已有 managed Context Scout，不要求 native spawn call；
2. 运行 HIGH/Human Checkpoint synthetic fixture；
3. 对旧 knowledge index 运行 `diagnose`；
4. 生成但不应用 migration candidate；
5. 验证 pre-sync warning 与 sync/archive hard failure；
6. 完成冻结的 Terra model review；
7. 仅当 Terra outcome 为 `inconclusive` 或 `block` 时继续验证 Task-level Human Checkpoint；
8. 最后确认 `git diff --stat` 和 `git status --short` 均为空。

最终通过记录见 `docs/acceptance/v5a-codex-20260805-final.md`。
