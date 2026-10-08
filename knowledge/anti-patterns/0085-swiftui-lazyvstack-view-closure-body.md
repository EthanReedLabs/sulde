---
doc_id: "ap-0085"
container: anti-patterns
platform: ios
summary: "SwiftUI LazyVStack 子 View 含 closure 参数 → 父 body 重算时子树永远无法跳过"
---

# 0085 — SwiftUI LazyVStack 子 View 含 closure 参数 → 父 body 重算时子树永远无法跳过

- **平台**:iOS
- **复发次数**:1

## 症状

列表卡片 body 重算次数远超状态变化次数（实测 18-20 次 / 卡 / 父 body 轮次），且**数据状态未变情况下仍重算**（如 `ready=true` 状态下重算 20 次）。即使已合并内部 @State 或后台预构建，滚动期仍有 100-200ms 主线程卡顿。

## 根因

列表卡片 View 的参数包含 closure:

```swift
ListCardView(
    ...
    onTap: { selectedCardId = item.id },   // closure — 每次父 body 重算时为新 instance
    onMuteTap: { isMuted.toggle() },        // closure — 每次父 body 重算时为新 instance
    onCreateTap: { store.send(...) }        // closure — 每次父 body 重算时为新 instance
)
```

closure 不是 Equatable → SwiftUI 每次父 body 重算时视这些参数为"已变化" → **强制子 body 重算**，无论数据实际是否变化。任何触发父 body 的 state/store 变化（如 loadMore、tag 切换）都连累所有可见卡片。

**实测数据**:
- 单卡 body 重算:18-20 次（ready 状态不变）
- fast swipe 爆发期:181 次/秒 body 调用
- 总计:3336 次 body 调用 / 84 秒（`Self._printChanges()` 插桩实测）

## 修复

列表卡片 View 接 `Equatable`，手动 `==` 跳过 closure 参数，在 `ForEach` 内加 `.equatable()` 修饰:

```swift
private struct ListCardView: View, Equatable {
    // ...
    let onTap: () -> Void
    let onMuteTap: () -> Void
    let onCreateTap: () -> Void

    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.item.id == rhs.item.id
            && lhs.isSelected == rhs.isSelected
            && lhs.isMuted == rhs.isMuted
            && lhs.cardWidth == rhs.cardWidth
            && lhs.height == rhs.height
        // closure 不比较:捕获的 @State binding / store 是引用类型，旧 body 保留时仍可正确调用
    }
}

// ForEach 内:
ListCardView(...).equatable()
```

## Equatable 安全性前提（不满足则不能用此方案）

closure 捕获的外部变量必须是**引用类型或 @State binding box**:
- `selectedCardId`（@State binding box）✅
- `isMuted`（@State binding box）✅
- `store`（StoreOf，引用类型）✅
- 如果 closure 捕获值类型且值会在父重算间变化 → 此方案不安全，需改用其他解法

## 判定线

```bash
# 检查 LazyVStack/ForEach 内是否有传 closure 参数的子 View
grep -n "onTap:\|onMuteTap:\|onCreateTap:\|onXxx:.*{" Sources/**/*.swift
# 命中且该子 View 未接 Equatable = 风险
grep -n "\.equatable()" Sources/**/*.swift
# 对应行数 == 0 = 未修复
```

## lint 状态

- 候选 lint:`rules/045-lazystack-closure-equatable.sh`（检测 ForEach 内 closure 参数子 View 缺 `.equatable()`）

## 关联

- 池复用黑屏（同属 LazyVStack 媒体卡片性能类）
- UI 时序约束（同属滚动 jank 系列）
- 滚动列表 onAppear action 风暴
