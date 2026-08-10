# 测试与数值验证策略

## 第一原则

对于算法和求解器功能，测试首先回答：

1. 功能是否真正参与了计算；
2. 外部结果是否正确；
3. 方向、符号、单位和路径行为是否正确。

不得因为内部函数、成员状态或分支被调用，就认为功能已经正确实现。

## 验证优先级

```text
工程/商业软件基准
→ 解析解或理论解
→ 业务级输入输出算例
→ 状态与路径行为
→ 网格、步长和极限敏感性
→ 局部算法函数
→ 实现细节
```

根据功能适用性选择层级，不要求每项全部具备。

## 测试分类

### 永久测试

保护真实缺陷、业务不变量、接口契约、高风险状态、数值理论和对标结果。

### 开发期测试

用于实验、定位和验证假设。任务结束时必须删除、合并或升级为有长期价值的永久回归测试。

### 机械性测试

只验证语言、标准库、简单赋值或 helper 调用，默认不创建。

## LOW Fast Path

LOW Fast Path 可以运行已有测试，也可以在行为完全明确时增加显然属于永久回归的 focused test。

如果为了定位未知问题必须新增临时探针、开发期断言或一次性测试，说明任务已经不再是纯 LOW Fast Path，应升级进入正式 Task/Change 或 Investigation，而不是把临时测试藏在 Fast Path 中。

## Investigation

探索阶段允许快速探针、实验断言和一次性算例，但应放入实验区或明确登记为 development-only/temporary。

实验测试不能通过修改正式基准、放宽容差或改变产品契约来获得通过。

## 测试 Seam

优先复用已有高层业务测试入口。只有外部行为无法定位公式错误或状态边界时，才新增更低层测试 seam。

## 修改已有测试

仅在测试明确错误、需求变化、批准后的契约变化、测试过度绑定内部实现或容差有过硬依据时允许。

## 容差

求解收敛容差修改为 HIGH；测试比较容差至少 MEDIUM。放宽必须说明误差来源和新边界依据。

## Test Finalization

新版本 Production Change 在进入正式 Review/后续收尾前必须执行明确的测试清理动作，而不是直接把 `test_cleanup_complete` 手工改成 `true`。

运行：

```powershell
python "$Runtime\finalize_tests.py" <change-id> --project $ProjectRoot `
  [--retain "tests/path=长期保留原因"] `
  [--preexisting "tests/path=任务开始前已有用户修改"]
```

Finalizer 会扫描当前 Git 工作区中的测试变化，并要求每个相关测试得到明确处置：

- `permanent-regression`：保留，必须给出长期保护价值；
- `development-only-removed`：开发期临时测试已经删除；
- `pre-existing-not-owned`：任务开始前已有的用户测试修改，不得由 Harness 擅自清理。

仍存在且未升级的 temporary test、未分类的新/改测试都会使 Finalization 失败。

成功后 Harness 写入 `test-finalization.yaml` 作为事务证据，并由该事务设置 `test_cleanup_complete` 和 `test_cleanup_evidence`。对于使用 `test_cleanup_protocol: 1` 的 Change，缺少该证据时正式 Review/后续生命周期必须失败。

## 清理原则

本任务新增的开发期测试应删除、合并或升级。删除任务开始前已有测试必须单独说明；当所有权不明确时优先保留并标记为 pre-existing，而不是自动删除。
