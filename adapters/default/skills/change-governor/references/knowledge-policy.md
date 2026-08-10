# 知识与共享语言策略

## 三类知识

1. `knowledge/`：人工审核的稳定架构事实；
2. `knowledge/glossary/`：项目精确术语和语义边界；
3. `knowledge/generated/`：非权威代码导航。

## 触发条件

以下变化应生成 Knowledge Sync 候选：

- 模块职责；
- 业务链和数据流；
- 状态所有权；
- 接口契约或生命周期；
- 设计决策；
- current/target/transitional/legacy/disputed 状态；
- 技术债关闭或新增；
- 项目术语定义变化；
- 商业软件对标与验收原则变化。

普通局部实现和失败实验通常不进入知识库。

## 共享语言

Glossary 条目应说明：

- Sitter 中的精确定义；
- 与常见含义的差异；
- 相关状态、公式或流程；
- 不应混用的相近词；
- 代码/测试证据。

## 审核

Agent 只生成候选。设计决策、target、legacy、disputed 和 glossary 定义必须人工审核。
