---
doc_id: "ap-0051"
container: anti-patterns
platform: cross
summary: "0051 iOS 底部抽屉禁 `.sheet` / `.fullScreenCover` → 必须用 BottomDr…"
---

# 0051 iOS 底部抽屉禁 `.sheet` / `.fullScreenCover` → 必须用 BottomDrawer ZStack overlay

- **平台**:iOS(确认) / Android(❌ N/A,BottomSheetDialogFragment 已统一)
- **复发次数**:1

## ❌ 错误 — 症状

设计稿"底部抽屉 / 分享面板 / 下载面板"(边到边底部,半透黑 backdrop 透出首屏),用 SwiftUI:
- `.sheet([.height(N)])` → 横向有 ~16-20pt **form-sheet 系统 inset**(iOS 18 行为,无干净 modifier 修法)
- `.fullScreenCover` → 宽度撑满 ✅,但 **backdrop 是不透明灰底**(UIWindow 系统灰),不是设计稿"半透黑"

外加 `.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)` 写法在 ZStack overlay 模式下会**撑满全屏**(无 detent 边界),违反 intrinsic 高度贴底设计。

## 为什么错(根因)

- iOS 18 `.sheet()` 即使 `.presentationDetents([.height(N)])` 也有 form-sheet 横向 inset,`.presentationBackground(.clear)` 仅去白底**不去 inset**
- `.fullScreenCover` 默认 `.fullScreen` presentation style,UIKit 优化掉底层 view → backdrop 透出来的是 UIWindow 系统灰
- `.modalPresentationStyle = .overFullScreen` 必须在 present 前设置,SwiftUI 不暴露这个 hook
- ZStack overlay 没有 detent,`maxHeight: .infinity` 撑满

## ✅ 正确 — 修法

**禁用** `.sheet()` / `.fullScreenCover()` 实现底部抽屉。**必须用** `BottomDrawer` ZStack overlay 同层渲染:

```swift
// AppRootView.mainStack
ZStack(alignment: .bottom) {
    tabBarHost
    shareDrawerOverlay
    downloadDrawerOverlay
}
```

子 View 写法:
```swift
// ❌ 旧 sheet 时代写法(撑满)
.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)

// ✅ ZStack overlay 写法(intrinsic)
.frame(maxWidth: .infinity, alignment: .top)
```

## 判定线

iOS Feature / View 内出现 `.sheet(` / `.fullScreenCover(` 包裹底部抽屉 / 分享 / 下载 → 违规。grep:

```bash
grep -rn "\.sheet(\|\.fullScreenCover(" Sources/Feature*/ Sources/CoreUI/  | grep -i "drawer\|share\|download\|bottom"
# 应 0 命中(底部抽屉类必走 BottomDrawer)
```

`maxHeight: .infinity` 在 ZStack overlay 子 View 内出现 → 红线:

```bash
grep -rn "maxHeight: \.infinity" Sources/Feature*/  # 凡是 BottomDrawer 内容子 View 不应有
```

## lint 状态

- iOS:⏳ TODO(grep 配上下文判断,误报率中等可作非阻断告警)
- Android:❌ N/A(BottomSheetDialogFragment + scaffold 已统一,无对应坑)

## 关联

- 框架脚手架规范「底部抽屉 / 弹窗」— iOS 侧从 sheet 转 ZStack overlay,规范需更新
- 自发修复边界 — 改 BottomDrawer 是 scaffold 层敏感字段
