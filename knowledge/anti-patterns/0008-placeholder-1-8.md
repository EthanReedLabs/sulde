---
doc_id: "ap-0008"
container: anti-patterns
platform: android
summary: "标题贴状态栏 / 三层根因"
---

# 0008 — 标题贴状态栏 / 三层根因

- **平台**:Android
- **复发次数**:≥ 3(同一症状,每次根因不同)

同一个"标题贴状态栏"bug 反复出现,每次根因不同但症状一样。三层根因:

| 第几次 | 直接症状 | 真正的根因 |
|:---:|---|---|
| 1 | 标题顶到状态栏底 | Activity 根本没接 inset(继承普通 AppCompatActivity 而非统一自适应基类)|
| 2 | 标题仍贴状态栏 | inset 工具用 `setPadding(inset.top, …)` **替换** XML 原 padding,业务 padding 静默丢失 |
| 3 | 间距仍偏紧 | 设计稿基于 iOS notched 状态栏(~62dp),Android 24-40dp,**视觉差 20-40dp 需业务补偿** |

```
层 3:iOS/Android 视觉尺寸差(长期存在)
  └→ 设计稿 iOS ~62dp+18dp padding ≈ 80dp
     Android 24-40dp+XML padding ≈ 32-48dp → 差 30-50dp,用户觉得紧
层 2:inset 工具是替换而非叠加(已修)
  └→ XML 写的 paddingTop 被 inset 直接覆盖,开发者不知道 XML 值被静默丢
层 1:Activity 没继承统一自适应基类(已修)
  └→ 没 fitConfig 入口,根本不响应 inset
```

## ❌ 错误一:在页面里硬编码 paddingTop

```kotlin
binding.title.setPadding(0, 24.dp, 0, 0)  // 状态栏高度靠猜
```

会在新设备/新 API level 再次出问题,且每个页面都要重复。

## ❌ 错误二:inset 工具里 setPadding 直接替换

```kotlin
fun applySystemBars(view: View) {
    ViewCompat.setOnApplyWindowInsetsListener(view) { v, insets ->
        v.setPadding(bars.left, bars.top, bars.right, bars.bottom)  // ← 覆盖 XML padding
    }
}
```

## ✅ 正确一:Activity 继承统一自适应基类 + 覆写 fitConfig

```kotlin
class XxxActivity : AdaptiveBaseActivity() {
    override fun fitConfig() = FitConfig(
        statusBar = true,
        navBar = true,
        keyboard = true   // 含输入的页面才设
    )
}
```

## ✅ 正确二:inset 工具叠加 base padding

```kotlin
fun applySystemBars(view: View) {
    // 记录 XML 原 padding 作为基线
    val baseLeft = view.paddingLeft
    val baseTop = view.paddingTop
    val baseRight = view.paddingRight
    val baseBottom = view.paddingBottom
    ViewCompat.setOnApplyWindowInsetsListener(view) { v, insets ->
        val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
        v.setPadding(
            baseLeft + bars.left,     // ← 叠加,不替换
            baseTop + bars.top,
            baseRight + bars.right,
            baseBottom + bars.bottom
        )
        insets
    }
}
```

## ✅ 正确三:根容器 paddingTop 做 Android 视觉补偿

```xml
<!-- 设计稿基于 iOS 上气口;Android 视觉补偿到 ≥ 24dp -->
<ScrollView
    android:paddingTop="24dp"
    android:paddingStart="20dp"
    android:paddingEnd="20dp"
    android:paddingBottom="24dp">
```

## lint 状态

- ✅ 本地 lint 脚本可检:
  - 规则 1:Activity 必须继承统一自适应基类(allowlist 例外)
  - 规则 2:根容器 paddingTop 若写死则 ≥ 16dp(或不写,走 inset)
- ⏳ 推荐接 pre-commit hook 自动跑。

**新页面 checklist**:
1. Activity 继承统一自适应基类?
2. 覆写 `fitConfig()` 声明需要的 inset?
3. 根容器 paddingTop ≥ 16dp(或留空交给 inset)?
4. 真机测试:状态栏到标题有 ≥ 30dp 视觉间距?
5. lint 通过?

关联:0001(同源原则 — 别在每页单独修系统级问题)、0012(MVI 基类缺继承,本条根因之一)。
