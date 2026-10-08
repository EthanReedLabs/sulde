---
doc_id: "ap-0004"
container: anti-patterns
platform: cross
summary: "颜色硬编码"
---

# 0004 — 颜色硬编码

- **平台**:Android / iOS(同类)

## ❌ 错误

```kotlin
view.setBackgroundColor(Color.parseColor("#0A0C11"))
```

## ✅ 正确

```kotlin
view.setBackgroundColor(Colors.bgPrimary)   // 引用 design token
```

## 为什么错

设计稿改色时,硬编码要全局搜索替换;design token 引用只改一处。

## lint 状态

- ✅ 静态可检:grep 源码内 `Color.parseColor("#...")` / `#RRGGBB` 字面量(排除 token 定义文件)→ 命中即报警。
