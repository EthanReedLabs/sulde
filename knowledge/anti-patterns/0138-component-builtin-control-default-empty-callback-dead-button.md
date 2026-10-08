---
doc_id: "ap-0138"
container: anti-patterns
platform: cross
summary: "0138 组件内建交互控件 + 默认空 callback → 死按钮 / 列表复用 placeholder 串台"
---

# 0138 组件内建交互控件 + 默认空 callback → 死按钮 / 列表复用 placeholder 串台

- **平台**:Android / iOS(跨端架构对照)
- **复发次数**:4+

## ❌ 错误

### Subcase A — 组件内建控件 + 默认空 callback → 死按钮

组件含**内建交互控件** + **默认空 callback**(`onLike: () -> Void = {}`),caller 引用时若漏传非空闭包 → 控件视觉可见但点了无反应:

```swift
struct FeedbackRow: View {
    var onLike: () -> Void = {}       // ⚠ 默认空 callback
    var onDislike: () -> Void = {}
    var body: some View {
        Button(action: onLike) { Image(systemName: "hand.thumbsup") }
        Button(action: onDislike) { Image(systemName: "hand.thumbsdown") }
    }
}

// 调用漏 wire → 默认空生效 → 死按钮:
MediaItemCard(item: frame)  // ❌ 没传 onLike/onDislike
```

```kotlin
// Android 同款:仅切可见性,无 setOnClickListener → 死按钮
binding.icThumbsUp.visibility = ...
```

### Subcase B — 列表/Pager 图片复用 placeholder → 封面串台

ViewHolder / Cell 复用时旧 drawable 当 placeholder,新图加载完成前闪现别条封面 → 用户感知"视频重复":

```kotlin
// ❌
val prev = thumbnail.drawable
loadImage(thumbnail, url) { placeholder(prev) }  // prev = 上一条封面

// ✅
thumbnail.setImageDrawable(null)   // 清旧图
loadImage(thumbnail, url)          // crossfade 从空过渡
```

## 为什么错

- A:默认空 callback 让"漏 wire"静默失败,组件视觉 ready 但未真挂载。
- B:回收复用架构(RecyclerView / LazyColumn / UICollectionViewCell dequeue)不显式清旧图就串台。iOS UIPageViewController + 每页新建 VC(无 dequeue 复用)架构天然规避 B。

## ✅ 正确

```swift
// A 修:caller 补 wire
MediaItemCard(item: frame, onLike: { store.send(.likeTapped) }, onDislike: { store.send(.dislikeTapped) })
```

| 架构 | Subcase B 风险 | 防护 |
|---|---|---|
| RecyclerView / Compose LazyColumn(回收复用)| ✅ 高发 | 必显式清旧图(`image = null` / prepareForReuse)|
| UIPageViewController + VC-per-item | ❌ 天然安全 | 实例不跨 item 复用 |
| UICollectionViewCell + dequeue | ✅ | prepareForReuse 显式清 |

教训:
1. **组件设计禁默认空 callback**:改 `var onLike: (() -> Void)? = nil` + `if let onLike { Button(...) }` 仅传值时渲染,OR 强制非 optional 入参。
2. caller 引用必 grep 全部 caller verify wire 非空。
3. 任一端发现死按钮 / 串台 → 必跨端 grep audit 同款(同组件设计 / 同复用模式)。

## lint 状态

⏳ — A:grep 组件定义 `on[A-Z]\w*: \(.*\) -> (Void|Unit) = \{\}` 默认空 callback,verify caller 是否传非空闭包。B:Android grep `.placeholder(...drawable...)`;iOS grep `prepareForReuse` 是否含 `imageView.image = nil`。

## 关联

- adapter wrap ≠ 真链路(A — 组件内建控件被伪装为已实施,实际死)
- boolean 语义不明(A — 空闭包语义不明,等同 disabled)
- Real adapter 委托 mock(B — 组件 ready 但未真挂载)
