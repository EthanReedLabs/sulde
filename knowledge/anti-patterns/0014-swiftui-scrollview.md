---
doc_id: "ap-0014"
container: anti-patterns
platform: ios
summary: "SwiftUI 固定区放 ScrollView 内 + 键盘自动顶整页"
---

# 0014 — SwiftUI 固定区放 ScrollView 内 + 键盘自动顶整页

- **平台**:iOS(Android `adjustPan` 有同源,`adjustResize` 是镜像方案)
- **复发次数**:2

## ❌ 错误(模式 1 — 应固定的搜索栏放在 ScrollView 内)

```swift
ZStack(alignment: .topLeading) {
    AppColors.bgPrimary.ignoresSafeArea()
    ScrollView {
        VStack(spacing: lg) {
            Text("Title")
            filterRow
            searchBar            // ← 应固定但放 ScrollView 内,会跟着滚走
            itemList
        }
    }
}
```

## ❌ 错误(模式 2 — 没加 `.ignoresSafeArea(.keyboard)`)

SwiftUI 默认 keyboard avoidance(iOS 14+)会调整整个 view 的 safe area 把整页顶起 → 用户点 searchBar → 顶部 title / filterRow 被推到屏幕外。

## ❌ 错误(模式 3 — GeometryReader-based modal overlay 内,键盘被算进 `safeAreaInsets.bottom`)

弹窗渲染在一个用 `GeometryReader` 固定 width×height 框的 overlay 内,overlay 用
`availableHeight = geometry.size.height − topInset − geometry.safeAreaInsets.bottom − bottomMargin`
算高度。键盘弹起 → `safeAreaInsets.bottom` 含键盘高度 → sheet 压缩,叠加根 ZStack 系统避让 → sheet 整体被顶出屏顶。

```swift
// ❌ 在最内层弹窗 view 内部加 ignoresSafeArea / 手动 padding —— 无效(推力来自祖先 overlay 层)
InnerSheetView {
    ...padding(.top, 250).ignoresSafeArea(.keyboard)  // 拦不住父层 GeometryReader
}
```

## 为什么错

- ScrollView 内的内容默认随滚动一起滚,把"应固定"的搜索栏/筛选栏当内容放进去 = 行为错位
- SwiftUI 默认 keyboard avoidance 调整整页 safe area,而非"只 ScrollView 区域上推"
- 模式 3:键盘高度通过祖先层的 `safeAreaInsets.bottom` 进入布局计算,最内层改无效

## ✅ 正确(模式 1/2)

```swift
ZStack(alignment: .topTrailing) {
    AppColors.bgPrimary.ignoresSafeArea()
    VStack(spacing: 0) {
        titleBar              // ← 固定区,放 ScrollView 之外
        filterRow             // ← 固定区
        searchBar             // ← 固定区
        ScrollView {
            VStack { itemList }   // 仅"内容"放 ScrollView 内
        }
        .scrollDismissesKeyboard(.immediately)  // ← 拖列表自动收键盘
    }
}
.ignoresSafeArea(.keyboard, edges: .bottom)     // ← 阻止整页被键盘顶起
```

## ✅ 正确(模式 3)

在 **overlay 调用层**(读取 `safeAreaInsets` 的那一层)关键盘避让,卡片靠内部手动 padding 抬起:

```swift
ModalSheetOverlay(topInset: 56, width: 370, height: 699, ...) {
    InnerSheetView(store: ...)
}
.ignoresSafeArea(.keyboard, edges: .bottom)   // ← 关掉这一层避让,GeometryReader 不再吃键盘

// 弹窗内部:监听 keyboardWillShow 高度 + 动态抬起
.padding(.top, max(60, 250 - keyboardHeight))
```

**判断口诀(模式 3)**:modal 内键盘遮挡,先 grep 弹窗挂载链(`ModalSheetOverlay` / `GeometryReader` / `.clipShape` — 弹窗是不是被框住),在"读取 `safeAreaInsets` 的那一层"关键盘避让,别在最内层瞎改。

**关键 modifier**:
- `.ignoresSafeArea(.keyboard, edges: .bottom)`:根容器加,阻止整页被顶起
- `.scrollDismissesKeyboard(.immediately)`:ScrollView 加,拖动即收键盘(iOS 16+)

**Android 镜像**:`windowSoftInputMode="adjustResize"`(非 `adjustPan`)— adjustPan 顶整页,adjustResize 仅缩内容区。

## lint 状态

- ❌ iOS 难静态扫描(modifier 顺序 + 跨文件语义需 AST)→ 人工 review:含 `TextField`/`TextEditor` 的页面查根容器是否有 `.ignoresSafeArea(.keyboard)` + ScrollView 是否有 `.scrollDismissesKeyboard`;modal 内有输入框查 overlay 层 `ignoresSafeArea(.keyboard)`
- ⏳ Android:`grep '<activity'` 检查含 EditText 页面是否标 `adjustResize`

**预防**:含输入框/列表的页面,设计阶段显式标注"哪些区域固定、哪些跟随键盘上推、键盘如何收回"。SwiftUI 默认行为不符合普通用户预期,必须主动覆盖。

关联:0015(Android 配套"点外部收键盘")。
