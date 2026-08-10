# Change 归档策略

## 归档前置条件

- `change.yaml` 状态为 ready-to-archive；
- proposal、design、tasks、verification、knowledge-sync、archive-summary 完整；
- Reviewer 不为 BLOCK；
- 未解决 blocker 为空；
- 临时生产文件为空；
- 实验残留已删除、隔离或登记；
- Knowledge Sync 已人工审核或明确标记 deferred。

## 归档处理

### 长期保留

- Change Artifacts；
- 经整理的对标算例与可复现脚本；
- ADR 和知识更新；
- 关键验证证据。

### 隔离保留

- 有研究价值但不属于生产实现的实验；
- 商业软件黑盒行为反演材料。

### 删除

- 临时日志、探针、失败补丁、重复输出、低价值开发期测试。

## 活跃任务清理

归档后 `.agent-work/<task-id>/` 默认删除；需要审计时只保留 `handoff.md` 或指向 Change 的索引。
