---
name: maintainer-handoff
description: Create a compact handoff for an active Sitter task when changing sessions, agents, or context windows. Use only for an existing task; do not duplicate content already stored in Change Artifacts, tests, diffs, or knowledge.
---

# Sitter Handoff

## Purpose

让新会话以最小上下文接手，不重复调查，不重新解释已有正式工件。

## 输入

读取：

- `.agent-work/<task-id>/task.yaml`；
- findings、grill decisions、实验记录和 review；
- 对应 `changes/<change-id>/`；
- 当前 Git 状态和最近验证结果。

## 输出位置

`.agent-work/<task-id>/handoff.md`

## 固定结构

1. 当前模式、阶段和双维度风险；
2. 已确认结论；
3. 当前推荐方案或批准后的 Change；
4. 未确认项；
5. BLOCK/WARN；
6. 关键证据和工件链接；
7. 已批准范围；
8. 下一步唯一动作；
9. 不要重复做的调查；
10. 临时代码和工作树状态。

## 压缩规则

- 不复制 proposal、design、测试日志或 Diff；
- 只引用路径和关键结论；
- 不写对话历史；
- 不加入未验证的新判断；
- 交接应足以让新 Agent 首先验证，而不是盲信。
