---
doc_id: "ap-0122"
container: anti-patterns
platform: cross
summary: "0122 客户端用占位逻辑伪造后端缺失的业务字段 → 占位与真实状态脱钩"
---

# 0122 客户端用占位逻辑伪造后端缺失的业务字段 → 占位与真实状态脱钩

- **平台**:iOS / Android
- **复发次数**:1

## ❌ 错误

后端列表项缺 `status` 字段 → 客户端用 `index % N` 分桶伪造状态:

```swift
static func mockStatus(index: Int) -> TaskItemStatus {
    let bucket = index % 10
    if bucket < 7 { return .completed }   // 列表最前(最新)100% 标 completed
    return .inProgress
}
```

- index 与真实业务状态**完全无关**。
- 列表倒序排列 → 最新提交(还在处理中)恰好落在 index 0~6 → **100% 被标 completed**。
- 用户看到"处理中的项出现在已完成"= 100% 复现的伪造态 bug。
- 占位本意是"让 UI 视觉完整",但占位逻辑产出了**错误的业务语义**(不是视觉占位,是状态造假)。

类似危险:把 unknown 默认到不可逆态 / 用随机数 / 用文件路径 hash 派生业务状态。

## 为什么错

- 占位只能补视觉,**禁补业务状态 / 能力判定**:封面图占位 ✓ / status 占位 ✗ / 可点击占位 ✗ / 已完成占位 ✗。
- 业务字段(enum 值 / status / amount / count)缺失 = 后端推单,不在客户端"造"。

## ✅ 正确

后端字段缺失 + 无可用查询 key 时,默认到**最安全语义**,绝不伪造危险态:

```swift
// 状态未知 → 默认 .inProgress(用户可见性最安全,operationally 不可逆动作禁默认完成)
let placeholderStatus: TaskItemStatus = .inProgress
// 并 escalate 后端补字段,FIXME 标记切真值路径
```

| # | 原则 |
|---|---|
| 1 | 占位只补视觉,禁补业务状态 / 能力判定 |
| 2 | 后端字段缺失时默认到最安全语义(不可逆动作禁默认"完成")|
| 3 | escalate + FIXME 标切真值路径,不靠脱钩逻辑(index / 随机 / 分桶 / hash)伪造;真值路径未到位前"暂空" > "假数据" |
| 4 | 业务字段必走后端真值,不允许客户端"补" |

## lint 状态

⏳ pending — 候选 grep `func mock\w*Status.*index` / `index % \d+.*\.(completed|success)`;语义脱钩 grep 不住,主靠人工 review。命中需 review:占位是封面图 ✓ / 业务字段 ✗。

## 关联

- mock 用 index 派生业务状态(同源,本反模式更具体)
- 跨端:另一端 Adapter 大概率同款 index-based 占位,需同款 fix
