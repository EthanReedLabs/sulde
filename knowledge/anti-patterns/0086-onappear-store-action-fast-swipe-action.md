---
doc_id: "ap-0086"
container: anti-patterns
platform: ios
summary: "滚动列表 `onAppear` 触发 store action → fast swipe 时 action 风暴"
---

# 0086 — 滚动列表 `onAppear` 触发 store action → fast swipe 时 action 风暴

- **平台**:iOS（Android 等价见下）
- **复发次数**:1

## 症状

fast swipe 时 store 状态反复翻转（如 `isLoadingMore` 反复 true→false），触发整页 body 反复重算，慢滑无问题但 fast swipe 卡顿。调查发现 loadMore 被同一卡片重复触发多次。

## 根因

分页列表末尾卡片的 `onAppear` 无守卫直接 send loadMore action:

```swift
.onAppear {
    if item.id == store.filteredItems.last?.id {
        store.send(.view(.loadMore))   // 无守卫
    }
}
```

fast swipe 时 last 卡反复进出视野（每次离开 + 进入都触发一次 onAppear）→ 短时间内多次 send → store 状态反复翻转 → `WithPerceptionTracking` 反复触发整 body → 连累所有可见卡片重算。

## 修复

`onAppear` 加 `!store.isLoadingMore` 守卫:

```swift
.onAppear {
    if item.id == store.filteredItems.last?.id,
       !store.isLoadingMore {               // ← 守卫:已在加载中就跳过
        store.send(.view(.loadMore))
    }
}
```

Reducer 层也可加 idempotent guard（action 到达时 `isLoadingMore` 已 true → 直接 `.none`），双重防护。

## 判定线

```bash
grep -n "loadMore\|\.onAppear.*last" Sources/**/*.swift
# 命中且无 !store.isLoading* 守卫 = 风险
```

## Android 等价

Compose:`LazyColumn` 内 `LaunchedEffect(key1 = isLastItem)` 触发加载 → 缺 `!isLoading` guard = 同一问题。修复:加 `if (!isLoading)` 条件。

## lint 状态

- 候选 lint:`rules/046-onappear-loadmore-guard.sh`

## 关联

- LazyVStack closure 参数 Equatable
- UI 时序约束
- LazyVStack 媒体卡片性能类
