---
doc_id: "ap-0136"
container: anti-patterns
platform: cross
summary: "0136 pen-truth 颜色 8 位 hex 跨端格式陷阱 — RGBA(设计稿)vs ARGB(Android…"
---

# 0136 pen-truth 颜色 8 位 hex 跨端格式陷阱 — RGBA(设计稿)vs ARGB(Android)vs opacity(iOS)

- **平台**:Android / iOS(跨端架构对照)
- **复发次数**:0

## ❌ 错误

pen-truth(设计稿提取真值)的颜色字段用 **8 位 hex** 表示透明度时,采用 **RGBA**(alpha 在尾)。例:`#FFFFFFB8` = 白色 + alpha `0xB8`(72%)。Dev 直接照抄字面:

```kotlin
// ❌ Android:Color.parseColor 是 ARGB(alpha 在头)
<color name="badge_text">#FFFFFFB8</color>
// → 解析为 R=255 G=255 B=184 A=255 → 不透明淡黄色!
```

```swift
// ❌ iOS:Color hex init 通常不接受 8 位 hex
.foregroundColor(Color("FFFFFFB8"))
// → 静默 fallback / 运行时异常 → 失去 72% 透明效果
```

## 为什么错

双端解析逻辑不同:Android `parseColor` 是 ARGB(alpha 头),设计稿是 RGBA(alpha 尾),照抄 → 解析成不透明偏色;iOS 多数 Color hex 扩展不接受 8 位 → 失透明 / 崩溃。

## ✅ 正确

| 维度 | 设计稿原值(RGBA)| Android(转 ARGB)| iOS(用 opacity)|
|---|---|---|---|
| 8 位 hex 格式 | `#RRGGBBAA` | `#AARRGGBB`(alpha 移头)| 不接受 8 位 / 用 opacity |
| 例 `#FFFFFFB8` | 白 + 0xB8(72%)| `#B8FFFFFF` | `Color.white.opacity(0.72)` |
| 例 `#3CFF5280` | 绿 + 0x80(50%)| `#803CFF52` | `Color("3CFF52").opacity(0.5)` |

```xml
<!-- Android:alpha 移到头 -->
<color name="badge_text">#B8FFFFFF</color>
```

```swift
// iOS:用 opacity modifier(0xB8/255 ≈ 0.72)
.foregroundColor(Color.white.opacity(0.72))
```

铁律:
1. 看到 pen-truth 颜色 8 位 hex 必转换,不照抄字面:Android 转 ARGB,iOS 用 `opacity()`。
2. 6 位 hex(`#RRGGBB`)双端通用,不需转换。
3. 协调端写 pen-truth 文档时,§视觉关键属性 段加"8 位 hex 是 RGBA,Android 转 ARGB,iOS 用 opacity"提示行;跨端 fix task md 起手含"颜色格式陷阱"章节。

## lint 状态

⏳ — Android:grep colors.xml 含 8 位 hex 且开头不是 alpha < 0xFF(疑似照抄)→ 警告 RGBA→ARGB 未转。iOS:grep `Color("8位hex")` / `Color(hex: "8位")` → 警告改 opacity。

## 关联

- 跨端镜像 L10n key 多用未 grep(同源跨端 sync 陷阱)
- 跨端 routing id 单 extra vs 分离参数(同源跨端架构 sync)
