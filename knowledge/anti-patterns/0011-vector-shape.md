---
doc_id: "ap-0011"
container: anti-patterns
platform: cross
summary: "视觉资源降级:渐变 / vector → 纯色 / 简单 shape 占位"
---

# 0011 — 视觉资源降级:渐变 / vector → 纯色 / 简单 shape 占位

- **平台**:Android / iOS(同源)
- **复发次数**:≥ 2

## ❌ 错误(Android drawable)

```xml
<!-- 卡片背景:缺渐变,实施成纯色白 -->
<shape android:shape="rectangle">
    <solid android:color="#FFFFFF"/>          <!-- ❌ pen-truth 真值是渐变 #18241A → #0E1217 -->
    <corners android:radius="20dp"/>
</shape>

<!-- 图标:lucide vector 实施成 shape rectangle 占位,变绿方块 -->
<shape android:shape="rectangle">
    <solid android:color="#3CFF52"/>          <!-- ❌ pen-truth 真值是 lucide arrow-up-right vector path -->
    <corners android:radius="2dp"/>
    <size android:width="12dp" android:height="12dp"/>
</shape>
```

## ❌ 错误同源(iOS)

```swift
Image(systemName: "square.fill")              // ❌ pen-truth 是 lucide arrow-up-right
    .foregroundColor(AppColors.accentPrimary)

.background(Color(hex: 0x18241A))             // ❌ pen-truth 是渐变 #18241A → #0E1217
```

## 为什么错

- Dev 不读 pen-truth 真值文档,直接按 view 现状或 PRD 文字描述占位实施
- pen-truth 渐变 / vector 数据完整(在视觉资源清单段),但 Dev 跳过这些段
- 用户实测看到的 = "颜色变了""箭头变方块",直接体验降级
- 以"占位"为名的纯色/简单 shape 一旦合并就**永久残留**(没人回头改)

## ✅ 正确

```xml
<!-- 严格按 pen-truth 渐变清单 -->
<shape android:shape="rectangle">
    <gradient android:type="linear"
        android:startColor="#18241A" android:endColor="#0E1217" android:angle="270"/>
    <corners android:radius="20dp"/>
</shape>

<!-- 用真 lucide vector(从共享图标源直接 cp) -->
<vector android:width="12dp" android:height="12dp"
    android:viewportWidth="24" android:viewportHeight="24">
    <path android:strokeWidth="2" android:strokeColor="#3CFF52"
        android:strokeLineCap="round" android:strokeLineJoin="round"
        android:pathData="M7 17 17 7 M7 7h10v10"/>
</vector>
```

```swift
LucideIcon.arrowUpRight.image                 // ✅ bundle SVG 真值
    .foregroundColor(AppColors.accentPrimary)

.background(LinearGradient(                   // ✅ 渐变还原
    colors: [Color(hex: 0x18241A), Color(hex: 0x0E1217)],
    startPoint: .top, endPoint: .bottom))
```

## lint 状态

- ⏳ Android:扫 drawable + 对照 pen-truth 渐变清单(pen-truth 标渐变但 drawable 用 `<solid>` 即报警)
- ⏳ iOS:`Image(systemName:)` 必须有同位置注释或在 SF fallback 表内
- 两端:人工 review 必查"pen-truth 视觉资源清单 vs 实际 drawable / Image"

**预防(UI 实施强制 4 步)**:
1. 先读 pen-truth 视觉资源清单(渐变 / lucide / 纯色 / image fill)
2. 实施时逐项对照
3. handoff 强制声明"各项已对照,实施 vs pen-truth 偏差为 0"
4. 任何"占位"实施必须在代码注释 + handoff 双重声明 `// TODO: 渐变 #XXX 待补`,占位本身是协调端待办

关联:0001(同源根因 — 不读真值)。
