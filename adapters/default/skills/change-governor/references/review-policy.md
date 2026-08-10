# 维护者反方审查

继续使用一个只读 Reviewer，但必须分别形成三个维度的判断。

## Architecture

检查：

- 第二套状态或第二套实现；
- 职责漂移、生命周期或接口语义变化；
- 承重墙不变量是否被破坏；
- 状态所有权和唯一真相来源；
- 与批准方案不一致。

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
- 是否用放宽容差、调参或特殊兜底凑结果。

## 输出

```text
Architecture: PASS / WARN / BLOCK
Scope: PASS / WARN / BLOCK
Numerical Evidence: PASS / WARN / BLOCK
Overall: PASS / WARN / BLOCK
```

主要发现按严重性排序，最多 8 条，每条附证据索引。Overall 不得优于最严重的单项结论。

## 多轮审查顺序

Reviewer 产出结果后，**先 `record-review`，再做任何 remediation**。BLOCK 也必须先按当前冻结 snapshot 正式落库，然后才修改实现、设计、测试或证据并进入下一轮。

一旦 remediation 改变了 diff / design / tasks / verification，旧 request 按设计应被判 stale；不要在修改输入后再尝试补录旧 Reviewer 结果，也不要手工篡改 request 来绕过 stale 检查。stale 原子拒绝用于保护审查证据与其实际输入的一致性。

BLOCK 必须交由用户决定。
