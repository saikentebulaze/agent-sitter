# Change Artifacts 规范

## 定位

Change Artifacts 是一次正式变更的持久承诺，不是调查笔记，也不是长期项目百科。

## 生命周期

```text
proposed → designed → approved → implementing → verifying → syncing → archived
```

## 文件职责

### change.yaml
机器可读状态、风险、批准、修改预算、Reviewer 和归档门。

### proposal.md
问题、根因、目标行为、范围、非目标、验收摘要。

### design.md
业务流程、职责模型、状态所有权、接口、生命周期、关键决策、备选方案。

### tasks.md
可执行切片、依赖、允许修改范围、验证和完成条件。

### verification.md
测试、工程/商业软件基准、业务不变量、误差口径、Reviewer 和剩余风险。

### knowledge-sync.md
需要新增、修改、关闭或保持不变的长期知识候选。

### archive-summary.md
根因、最终方案、职责 Diff、验证、知识同步、剩余债务的压缩总结。

## 边界

- Investigation 的假设和失败尝试不复制进正式 Change；
- Change 只记录批准后的目标和必要证据；
- 具体文件路径可放 tasks，长期设计文档避免过度绑定临时路径；
- Change 完成不意味着知识自动生效。
