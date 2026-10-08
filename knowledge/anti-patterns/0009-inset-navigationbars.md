---
doc_id: "ap-0009"
container: anti-patterns
platform: android
summary: "底栏 inset 误用 navigationBars + 容器固定高度"
---

# 0009 — 底栏 inset 误用 navigationBars + 容器固定高度

- **平台**:Android(iOS `.safeAreaInset` 语义不同,需差异化设计)
- **复发次数**:1

## ❌ 错误

```kotlin
// 只读 navigationBars + 加法
fun applyNavBar(view: View) {
    val base = view.paddingBottom
    ViewCompat.setOnApplyWindowInsetsListener(view) { v, insets ->
        val nav = insets.getInsets(WindowInsetsCompat.Type.navigationBars()).bottom
        v.setPadding(..., base + nav)   // 加法 + 只读 navigationBars
    }
}
```

```xml
<!-- 底栏容器硬编码高度 -->
<LinearLayout
    android:layout_height="95dp"
    android:paddingBottom="21dp"
    android:gravity="center">
    <LinearLayout android:id="@+id/nav_bar" android:layout_height="62dp" />
</LinearLayout>
```

## 为什么错

- Android 12+ 语义变化:`navigationBars` 只报手势条最小区(~16dp),三键按钮真实高度挂在 `mandatorySystemGestures`(~44dp)。只读前者 → 三键模式下 padding 不够 → 底栏被盖住
- 加法 `base + inset` 在三键模式下叠加过多,变成"设备越新越宽松"的反直觉间距
- 容器固定 `height` + 内部 `nav_bar` 固定高度 → paddingBottom 可用空间被挤死,nav_bar 永远不会真的上移

## ✅ 正确

```kotlin
fun applyNavBar(view: View) {
    val base = view.paddingBottom
    val breathing = dpToPx(8)
    ViewCompat.setOnApplyWindowInsetsListener(view) { v, insets ->
        val nav = insets.getInsets(WindowInsetsCompat.Type.navigationBars()).bottom
        val mandatory = insets.getInsets(WindowInsetsCompat.Type.mandatorySystemGestures()).bottom
        val effective = maxOf(nav, mandatory)   // ← 取两者最大值
        v.setPadding(..., maxOf(base, effective + breathing))
    }
}
```

```xml
<!-- 容器高度自适应,paddingBottom 由 applyNavBar 动态撑开 -->
<LinearLayout
    android:layout_height="wrap_content"
    android:paddingTop="6dp"
    android:paddingBottom="21dp">
    <LinearLayout android:id="@+id/nav_bar" android:layout_height="62dp" />
</LinearLayout>
```

**三模式实测**:

| 模式 | nav inset | mandatory inset | effective | paddingBottom |
|------|:--:|:--:|:--:|:--:|
| 手势导航 | 16dp | 16dp | 16dp | 24dp |
| 虚拟三键 | 16dp | 44dp | 44dp | 52dp |
| 实体 / 全屏 | 0 | 0 | 0 | 21dp(base 保底) |

## lint 状态

- ⏳ Android:可写 lint 规则(底栏容器高度禁写死 + applyNavBar 必取 max(nav, mandatory))
- ⏳ iOS:需差异化设计(`.safeAreaInset` 语义不同)
- 人工 review:新底部浮层/底栏容器 PR 挂 checklist
