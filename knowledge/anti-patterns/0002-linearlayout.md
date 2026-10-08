---
doc_id: "ap-0002"
container: anti-patterns
platform: android
summary: "浮层用 LinearLayout 排列"
---

# 0002 — 浮层用 LinearLayout 排列

- **平台**:Android

## ❌ 错误

```xml
<!-- 把"浮层按钮 + 操作栏 + 内容区"用 LinearLayout 排成一列 -->
<LinearLayout orientation="vertical">
    <ImageView 浮层按钮 />
    <FrameLayout 内容区 />
    <LinearLayout 操作栏 />
</LinearLayout>
```

## 为什么错

浮层应该叠在内容上方,不是排在内容下面。LinearLayout 把它们排开了。

## ✅ 正确

```xml
<FrameLayout>
    <FrameLayout 内容区 match_parent />
    <ImageView 浮层按钮 layout_gravity="start|top" marginStart=18dp marginTop=18dp />
    <LinearLayout 操作栏 layout_gravity="end|bottom" marginEnd=18dp marginBottom=152dp />
</FrameLayout>
```

**判断规则**:设计稿 layout=none(子项绝对定位/叠放)→ 用 FrameLayout,子项 layout_gravity + margin 定位。

## lint 状态

- ❌ 难静态检查(需理解设计稿叠放语义 vs 布局类型)→ 人工 review。
- 关联:0006(SwiftUI 同源 — 浮层误用 VStack/HStack)。
