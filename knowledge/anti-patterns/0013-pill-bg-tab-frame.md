---
doc_id: "ap-0013"
container: anti-patterns
platform: cross
summary: "选中态 pill bg 撑满整个 tab frame"
---

# 0013 — 选中态 pill bg 撑满整个 tab frame

- **平台**:iOS / Android(同源,根因镜像)
- **复发次数**:1(双端同时踩)

## ❌ 错误(iOS)

```swift
VStack { icon; label }
    .frame(maxWidth: .infinity)        // ← 先撑满分配空间
    .frame(width: tabWidth)            // ← 再固定宽度
    .background(...)                   // ← bg 包整个 tab frame → pill 撑满挨相邻按钮
    .clipShape(...)
```

## ❌ 错误(Android)

```kotlin
val tabView = LinearLayout(this).apply {
    layoutParams = LayoutParams(0, MATCH_PARENT, 1f)  // weight=1 平均分配
    background = bg_nav_tab_active                     // ← bg 在外层 tabView,撑满整格
    addView(icon); addView(label)
}
```

## 为什么错

- Tab 数减少后分配宽度变大 → bg pill 撑满 → 视觉是大椭圆挨到旁边按钮,不符合设计稿(pill 应紧贴 icon+text 视觉宽)
- 设计稿明确 pill 是"内容容器尺寸 + 横向 padding"包出的小椭圆,不撑满

## ✅ 正确(iOS)

```swift
VStack { icon; label }
    .padding(.horizontal, 16)          // ← 内容横向 padding
    .frame(height: 54)                 // ← 固定高度
    .background(...)                   // ← bg 包内容 + padding
    .clipShape(...)
    .frame(maxWidth: .infinity)        // ← clipShape 之后再撑满分配空间(tap 区扩到全宽)
```

## ✅ 正确(Android — 2 层结构)

```kotlin
val tabView = FrameLayout(this).apply {                  // ← outer = tap area, no bg
    layoutParams = LayoutParams(0, MATCH_PARENT, 1f)
}
val contentLayout = LinearLayout(this).apply {           // ← inner = bg pill, wrap_content
    orientation = VERTICAL
    setPadding(dp16, 0, dp16, 0)
    background = bg_nav_tab_active                       // ← bg 在内层,wrap_content → pill 紧凑
    gravity = Gravity.CENTER
    addView(icon); addView(label)
}
tabView.addView(contentLayout)
tabBgViews[id] = contentLayout                           // ← 切 bg 时操作内层
```

**根因总结**:bg 必须应用在**内容尺寸的容器**上,再由外层(maxWidth / FrameLayout match_parent)扩 tap 区。两端都是把 bg 错误地放在"分配空间的容器"上。

## lint 状态

- ❌ 难静态扫描(SwiftUI modifier 顺序 / View 层级需 AST 分析)→ 人工 review。

**预防**:做带 bg 的紧凑容器(pill / chip / badge)时,先想清 bg 包多大:
- 内容大小 → bg 放最内层
- 分配空间 → bg 放最外层
- 两者都不是 → 用嵌套结构(Android 两层 / iOS modifier 顺序控制)

关联:单状态截图易误判布局(见 0141)。
