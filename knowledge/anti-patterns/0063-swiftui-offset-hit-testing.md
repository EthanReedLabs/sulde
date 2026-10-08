---
doc_id: "ap-0063"
container: anti-patterns
platform: ios
summary: "0063 SwiftUI `.offset` hit-testing 不随渲染移动"
---

# 0063 SwiftUI `.offset` hit-testing 不随渲染移动

- **平台**:iOS
- **复发次数**:1

## ❌ 错误

弹窗键盘遮挡修复后,**输入完按钮置灰点不到**:

- 键盘适配用 `.offset(y: -keyboardHeight / 2)` 把 modal 视觉上移 ✅
- 但**按钮 hit-testing 仍在原位置**(键盘下方 / 屏幕外)
- 用户点不到按钮 = 视觉错位 + 功能回归

## 为什么错

SwiftUI 已知坑:

| API | 视觉效果 | hit-testing 区域 |
|---|---|---|
| `.offset(y: -h)` | view 视觉上移 | ⚠️ **不随移动** — hit area 仍在原 frame |
| `.padding(.bottom, h)` | 容器 frame 缩小 | ✅ 跟随 — hit area 在新 frame |
| `.position(x:y:)` | view 重新定位 | ✅ 跟随 |
| `.transformEffect(...)` | 矩阵变换 | ⚠️ 不随移动 |

`.offset` 是渲染层 visual offset,SwiftUI 默认不重计算 hit-test rect。

## ✅ 正确

键盘适配 / 动画 push view 等需要真移动 frame 的场景,**禁用 `.offset`**,改用 `.padding` / `.position` 让 frame 真改变:

```swift
public func body(content: Content) -> some View {
    VStack(spacing: 0) {
        Spacer(minLength: 0)
        content
        Spacer(minLength: 0)
    }
    .padding(.bottom, keyboardHeight)         // ← 用 padding 改 frame(非 .offset)
    .animation(.easeOut(duration: 0.25), value: keyboardHeight)
}
```

**判定线**:SwiftUI 键盘适配 / 动画 push view / 任何"渲染层与 hit-test 都需移动"场景 — 禁用 `.offset` / `.transformEffect`。

## lint 状态

- 协调端 task md 涉及 view push / 动画时,自检"用 padding/position 而非 offset";
- 难自动 lint(SwiftUI 内部行为,grep 无法精确判)。

## 关联

- 0061(协调端凭印象不查技术真值)— 父类
