# 维护者反方审查

继续使用一个只读 Reviewer，但必须分别形成三个维度的判断。对于 `candidate_readiness_protocol: 1` 的新 Change，这一轮正式 independent review 是 **Candidate Readiness Review**：它发生在用户验收前，目的是确保交给人的不是半成品。

## Architecture

检查：

- 第二套状态或第二套实现；
- 职责漂移、生命周期或接口语义变化；
- 承重墙不变量是否被破坏；
- 状态所有权和唯一真相来源；
- 与批准方案不一致；
- 明显不优雅、重复责任或局部补丁式实现是否意味着遗漏了更合适的框架入口。

## Scope

检查：

- 超出修改预算；
- 顺手重构或无关格式化；
- 多余 helper、抽象、缓存、配置、日志、异常、fallback、兼容层；
- 相邻问题是否未经批准被修改；
- 低价值测试膨胀。

## Numerical Evidence

检查：

- 功能是否真正参与计算；
- 外部位移、反力、内力、应力或状态结果是否正确；
- 坐标、方向、符号、单位和结果口径；
- 加载、卸载、重载、开闭、屈服或历史路径；
- 解析解、工程基准或商业软件对标；
- 是否只验证内部变量而未验证外部行为；
- 是否用放宽容差、调参或特殊兜底凑结果；
- Readiness Contract 中的代表性算例是否真的穿过目标业务链，而不是旁路或只覆盖局部 helper。

## 输出

正文先给主要发现，按严重性排序，最多 8 条，每条附证据索引。结尾必须包含机器可解析尾块：

```yaml
sitter_review:
  architecture: pass|warn|block
  scope: pass|warn|block
  numerical_evidence: pass|warn|block
  remediation_route: implementation|awaiting-production-design|null
```

Overall 由 Harness 按最严重维度派生，不由 Reviewer 单独决定。

## BLOCK 的两类语义

`implementation` 表示问题可在已经批准的 Design、Scope、User Decision 内确定性修复，例如：遗漏已有业务分支、职责/结构明显不佳、测试只覆盖内部变量、代表性算例没有真正经过目标链路、临时调试残留或证据不足。此类 BLOCK 应自动回到 `implementing`，Agent 修复并重新完成 readiness/review，默认不打断用户。

`awaiting-production-design` 表示修复需要新的工程/产品决定，例如扩大 Scope、改变算法/数值语义、坐标/符号/单位、兼容/fallback policy、acceptance contract，或与已记录用户决定冲突。只有这类 BLOCK 才升级到 human checkpoint。

## 多轮审查顺序

Reviewer 产出结果后，必须先正式 record，再做 remediation。BLOCK 也先按当前冻结 snapshot 落库，然后才修改实现、设计、测试或证据并进入下一轮。

一旦 remediation 改变 production snapshot / Design / Tasks / Change Budget / authoritative user decisions / Readiness Contract，旧 review 应判 stale。单纯新增 final verification PASS evidence、渲染 Markdown 或写 Harness 自身状态不应使已经审过的 production candidate 失效。

旧 V6 Change 继续使用 snapshot protocol 1；V6.2 新 Change 后续切换到 production/readiness-aware snapshot protocol 2。
