---
doc_id: "ap-0088"
container: anti-patterns
platform: ios
summary: "SwiftUI Button `.frame()` 无 `.contentShape()` 致 hit-testing…"
---

# 0088 — SwiftUI Button `.frame()` 无 `.contentShape()` 致 hit-testing 命中区偏小

- **平台**:iOS
- **复发次数**:1
- **lint 状态**:⏳ 待建（`rules/006-swiftui-button-hit-area.sh`，grep 软警告粗版已有草稿）

## 现象

Button 用 `.frame(width: 44, height: 44)` 在视觉上把 icon 扩到 44pt HIG 标准 tap target，但用户反馈"按钮迟钝 / 按不到"。实测命中区只有 icon 渲染内容本身（chevron 字形约 20×20pt）。

## 根因

SwiftUI 的 `.frame()` modifier 只改 **layout 区域**，不改 **hit-testing 形状**。Button 的点击区跟随其 label 内实际渲染内容（字形 / 图片像素），而非 frame 给出的矩形。

## 修法

Button label 内，`.frame(width:height:)` 之后加 `.contentShape(Rectangle())`:

```swift
// ❌ 错误:frame 扩到 44 但命中区仍 ~20×20
Button { onBack() } label: {
    Icon.chevronLeft.image
        .font(.system(size: 20, weight: .semibold))
        .frame(width: 44, height: 44)
}

// ✅ 正确:contentShape 让整 frame 参与 hit-testing
Button { onBack() } label: {
    Icon.chevronLeft.image
        .font(.system(size: 20, weight: .semibold))
        .frame(width: 44, height: 44)
        .contentShape(Rectangle())   // ← 必须紧跟 .frame()
}
```

关联:Apple HIG "Minimum 44pt × 44pt tap target"。

## lint 草稿

`rules/006-swiftui-button-hit-area.sh`（软警告，误报概率存在）:

```bash
grep -rln "Button {" Sources --include="*.swift" 2>/dev/null | while read f; do
    if grep -qE "\.frame\(width:.*height:" "$f" && \
       grep -q "Button" "$f" && \
       ! grep -q "\.contentShape" "$f"; then
        echo "⚠️  $f 含 Button + .frame(width:height:) 但无 .contentShape — 可能 hit-test 命中区偏小"
    fi
done
```
