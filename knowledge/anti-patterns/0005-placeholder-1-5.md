---
doc_id: "ap-0005"
container: anti-patterns
platform: android
summary: "主内容区固定高度"
---

# 0005 — 主内容区固定高度

- **平台**:Android

## ❌ 错误

```xml
<CardView android:layout_height="658dp" />  <!-- 设计稿是 658,直接写死 -->
```

## 为什么错

不同屏幕高度差 100dp+,固定值会导致小屏溢出、大屏底部留白。

## ✅ 正确

```xml
<CardView android:layout_height="0dp" android:layout_weight="1" />
```

**原则**:设计稿标注的是某一参考屏的绝对高度,跨屏主内容区应用 weight / 比例 / 约束自适应,不照搬绝对值。

## lint 状态

- ❌ 难静态检查(固定高度有时合理)→ 人工 review 大块内容区是否写死高度。
