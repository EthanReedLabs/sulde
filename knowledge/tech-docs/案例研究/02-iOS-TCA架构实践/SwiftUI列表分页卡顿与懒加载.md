---
doc_id: "tech-docs/案例研究/02-iOS-TCA架构实践/SwiftUI列表分页卡顿与懒加载"
container: case-studies
platform: none
summary: "**技术域**：iOS 性能工程 / SwiftUI / Perception 状态观察 **难度**：⭐⭐⭐⭐⭐ *…"
---

# SwiftUI 列表分页卡顿与懒加载案例研究

> **技术域**：iOS 性能工程 / SwiftUI / Perception 状态观察
> **难度**：⭐⭐⭐⭐⭐
> **关键词**：SwiftUI / VStack / LazyVStack / WithPerceptionTracking / ScrollViewReader / CADisplayLink / ForEach / .id() / .onAppear / store 观察 / HITCH / 主线程
> **可迁移场景**：长列表分页、音乐/素材选择页、无限滚动列表、状态驱动列表、分页 append、异步补齐时长/封面/元数据的列表

---

## 场景与系统架构

某 iOS 音乐长列表页采用 SwiftUI 实现。页面首屏加载一批数据，用户滚动到底部时，最后一行的 `.onAppear` 触发 `loadMore`，远端返回下一页后 append 到列表。列表同时还会异步补齐每首歌的时长信息，时长合并后刷新对应行展示。

简化结构如下：

```swift
ScrollViewReader { proxy in
    ScrollView {
        VStack {
            WithPerceptionTracking {
                ForEach(store.items) { item in
                    RowView(item: item)
                        .id(item.id)
                        .onAppear {
                            if item.id == store.items.last?.id {
                                store.send(.loadMore)
                            }
                        }
                }
            }
        }
    }
}
```

状态链路：

```
用户滚动到底部
└── last row .onAppear
    └── store.send(.loadMore)
        └── 网络请求下一页
            └── append +20 items
                └── SwiftUI 重新计算列表 body
                    └── 行重建 / 布局 / 主线程帧阻塞
```

另一路异步时长合并：

```
后台获取时长
└── 分批 merge 到 durationCache
    └── store 变化
        └── WithPerceptionTracking 重新评估
            └── 列表行重建
```

问题出在两点叠加：外层是非懒加载 `VStack`，并且所有行被包在单个 `WithPerceptionTracking` 内。每次列表 append 或缓存变化，整个列表都可能被重新评估和重建。

---

## 问题现象

用户滚到列表底部触发下一页加载时，界面会明显抖动、卡顿一下；持续翻页时每次 append 都有类似卡顿。

实测数据：

| 指标 | Before |
|---|---:|
| 每次 loadMore append 主线程 HITCH | 207~285ms，均值约 240ms |
| 60Hz 掉帧数 / 次 append | 约 12~17 帧 |
| 行重建数 Δ / 次 append | 当前总数 + 20 |
| 8 页 / 166 项累计行重建 | 1052 次 |
| 时长合并触发 HITCH | 40~56ms / 批 |

关键时间线节选：

```text
append +20 total=20    -> HITCH 207.9ms rowBuilds=40
loadMore trigger      -> HITCH 249.8ms rowBuilds=100
append +20 total=60
loadMore trigger      -> HITCH 226.8ms rowBuilds=280
append +20 total=100  -> HITCH 285.7ms rowBuilds=400
duration merge batch  -> HITCH 34.2ms rowBuilds=400
```

两个信号非常关键：

1. 200ms+ 大 HITCH 全部紧贴 append / loadMore 时间戳。
2. 行重建 Δ = `total + 20`，说明每次 append 后整列表所有行都被重新 build。

这不是普通的网络慢，也不是单张图片解码慢，而是分页 append 后主线程集中重建列表。

---

## 根因分析

### 根因一：非懒加载 `VStack` 导致 append 时整列表重建

`VStack` 会构建其 body 中的所有子视图。列表较短时问题不明显；当列表不断 append，`ForEach` 中已有行越来越多，每次新增 20 行都可能触发全量 body 计算。

非懒加载结构：

```swift
ScrollView {
    VStack {
        ForEach(items) { item in
            RowView(item: item)
        }
    }
}
```

第 1 页 append 后构建 20 行，第 2 页 append 后构建 40 行，第 3 页 append 后构建 60 行……累计成本接近：

```
20 + 40 + 60 + 80 + ... + N = O(N²)
```

实测行重建 Δ = `total + 20` 正好吻合这个模型。每次 append 的新数据只有 20 行，但主线程要重新走当前全部行的构造和布局，因此出现 207~285ms 的长帧。

### 根因二：单个 `WithPerceptionTracking` 包住所有行，观察粒度过粗

`WithPerceptionTracking` 的作用是追踪被访问的 store 状态，并在相关状态变化时触发重新计算。如果整个列表都包在一个 tracking 区域内：

```swift
WithPerceptionTracking {
    ForEach(store.items) { item in
        RowView(
            item: item,
            duration: store.durationCache[item.id]
        )
    }
}
```

那么 `store.items` append 或 `store.durationCache` merge 都可能让整个 tracking 区域重新评估。即使某次 duration merge 只影响几个可见或不可见 item，也会把全列表置于重评估范围内。

这解释了两个现象：

1. append 是最大 HITCH，因为 `items` 本身变化，所有行重建。
2. duration merge 是中等 HITCH，因为缓存变化也触发列表重评估，大列表时每批 40~56ms。

Perception 本身不是问题；问题是观察边界太粗。状态观察应尽量贴近真正需要变化的子视图。

### 根因三：CADisplayLink 长帧 + 行重建计数器能定位主因

本次定位使用了三类临时探针：

1. `CADisplayLink` 长帧探测：记录超过 24ms 的 frame。
2. append / merge 时间戳：标记 loadMore、append、duration merge 的发生时间。
3. 行重建计数器：每次 row body 构建时计数。

组合后可以形成证据链：

```
append 时间戳
└── 紧贴 200ms+ HITCH
    └── rowBuilds 同步大幅增加
        └── Δ = 当前 total + 20
            └── 整列表重建，而非单行或网络
```

这也排除了其他常见假说：

| 假说 | 排除依据 |
|---|---|
| 图片解码慢 | HITCH 与 append/merge 时间戳对齐，不与图片加载点对齐 |
| 网络慢 | 网络在后台，长帧发生在数据 append 到 UI 后 |
| 单项时长更新太频繁 | 已做分批合并，但每批仍重渲全列表，根因仍是列表重建范围 |

### 根因四：历史 LazyVStack 回归风险来自身份稳定性

素材中提到该列表历史上曾担心 `LazyVStack` 导致选中态身份错乱。这个风险是合理的：懒加载容器会按需创建和回收子视图，如果行身份不稳定，选中态、展开态、ScrollViewReader 定位都可能错位。

当前修复前提是每行已有稳定身份：

```swift
RowView(item: item)
    .id(item.id)
```

`.id(item.id)` 让 SwiftUI 和 `ScrollViewReader` 能基于业务 id 识别行，而不是依赖临时位置。这样可以降低从 `VStack` 切到 `LazyVStack` 的身份风险。

---

## 解决方案

### 方案：`VStack` 改为 `LazyVStack`

核心改动是把非懒加载容器替换为懒加载容器：

```swift
ScrollViewReader { proxy in
    ScrollView {
        LazyVStack {
            WithPerceptionTracking {
                ForEach(store.items) { item in
                    RowView(item: item)
                        .id(item.id)
                        .onAppear {
                            if item.id == store.items.last?.id {
                                store.send(.loadMore)
                            }
                        }
                }
            }
        }
    }
}
```

`LazyVStack` 只构建当前可见区域和附近缓冲区域的子视图。append 后，不再需要立即构建历史所有行，主线程成本从“当前列表总数”下降到“可见/已实现行数”。

### 回归点

从 `VStack` 切换到 `LazyVStack` 后，需要重点回归：

1. 选中态 inline 展开是否仍对应正确行。
2. `ScrollViewReader.scrollTo` 是否仍能定位正确 id。
3. loadMore 的 `.onAppear` last row 是否仍稳定触发。
4. prepend / placeholder / 分页边界是否会造成滚动跳动。

`.id(item.id)` 是降低这些风险的关键。没有稳定 id 时，不建议贸然切 LazyVStack。

### Before / After 实测

| 指标 | Before：VStack | After：LazyVStack | 改善 |
|---|---:|---:|---:|
| append 主线程 HITCH | 207~285ms，均值约 240ms | 82~133ms，max 133ms | 约 2.4x |
| 累计 rowBuilds | 1052 | 266 | 约 4x |
| append 200ms+ 大卡次数 | 8/8 | 0 | 大卡消除 |
| 每次 append Δ 行重建 | `total + 20` 全列表 | 50~100 已实现行 | 懒加载部分生效 |

这说明主因确实是非懒加载列表全量重建。切换 LazyVStack 后，200ms+ 大卡消失，用户体感变流畅。

### 残留与边界

修复后 append 仍有 82~133ms，超过一帧预算。原因是外层仍有非懒加载结构包裹，部分抵消了 LazyVStack 的收益。进一步优化方向是把外层结构也 flatten，让 LazyVStack 成为更直接的滚动内容容器。

但这会牵涉共享列表结构和更多回归面。当前实测已经消除 200ms+ 大卡，继续深挖 ROI 下降，因此可作为后续优化项。

### 为什么这样修，而不是只降低 merge 频次

降低 duration merge 频次能减少 40~56ms 中等 HITCH，但不能解决 append 主因。append 每次仍会触发整列表重建，200ms+ 大卡仍然存在。

换句话说：

```
降低 merge 频次：减少次因
VStack -> LazyVStack：解决主因，并顺带减轻 merge 重渲范围
```

因此优先修列表容器策略，而不是只在数据层继续降频。

---

## 可迁移原则

### 1. 长列表不要用非懒加载容器承载分页内容

`VStack` 适合小规模静态内容；分页长列表应优先使用 `LazyVStack` 或 `List`。否则 append 会让累计构建成本接近 O(N²)。

### 2. 状态观察粒度要贴近行

一个 `WithPerceptionTracking` 包住整列表，会让任意列表或缓存变化触发全区域评估。长列表应尽量把观察粒度下沉到行或子组件，减少无关行重建。

### 3. 用长帧和 row build 计数证明瓶颈

只看“滚动卡”无法判断是图片、网络、数据 merge 还是布局重建。`CADisplayLink` 长帧 + 时间戳 + row build 计数可以把 HITCH 与具体状态变化对齐。

### 4. Lazy 容器切换必须配稳定身份

懒加载会复用和延迟创建子视图。`ForEach` 应使用稳定业务 id，并配合 `.id(item.id)` 保护选中态、展开态和 scrollTo 行为。

### 5. 优先修结构性 O(N²)，再修局部频次

如果每次 append 都全量重建，降低某个辅助状态 merge 频次只是治标。先把列表构建复杂度降下来，再优化局部更新频率。

### 6. 性能优化要保留 before/after

本案例能确认修复命中根因，是因为保留了 append HITCH、rowBuilds、200ms+ 大卡次数的前后对比。没有 before/after，很容易把体感改善误判为偶然。

---

## 技术深问 Q&A

### Q1：为什么 `VStack` 会导致分页列表 O(N²)？

因为每次 append 后，`VStack` 会重新构建所有子视图。分页增长时，第 1 次构建 20 行，第 2 次 40 行，第 3 次 60 行，累计成本随页数平方增长。

### Q2：`LazyVStack` 为什么能降低 append 卡顿？

它只实例化可见区域和附近缓冲区域的子视图。append 新数据后，不需要立即构建历史所有行，因此主线程 row build 和布局成本显著下降。

### Q3：为什么 `WithPerceptionTracking` 会影响重建范围？

它会追踪闭包中读取的状态。如果闭包包住整列表，并读取 `store.items` 和 `durationCache`，这些状态变化时整个闭包都可能重新评估，进而影响所有行。

### Q4：为什么图片解码被排除了？

长帧时间点紧贴 append / loadMore / duration merge，而不是图片加载或解码事件；同时 rowBuilds 在长帧附近大幅增长，说明主线程忙于重建列表。

### Q5：为什么修后仍有 82~133ms？

LazyVStack 降低了行构建范围，但外层仍有部分非懒加载结构和状态观察开销。要进一步压低，需要更大范围 flatten 容器和细化观察粒度。

### Q6：什么时候不该直接换 LazyVStack？

如果行身份不稳定、选中态依赖 index、`scrollTo` 使用临时位置、或展开态绑定在 View 本地状态里，直接切 LazyVStack 可能引发错位。应先补稳定 id 和状态归属。
