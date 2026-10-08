---
doc_id: "ap-0015"
container: anti-patterns
platform: android
summary: "Android EditText 页面应继承统一基类默认\"点外部收键盘\""
---

# 0015 — Android EditText 页面应继承统一基类默认"点外部收键盘"

- **平台**:Android(iOS 待镜像 ViewModifier)
- **复发次数**:2

## ❌ 错误

每个含 `EditText` 的 Activity 都自做 `dispatchTouchEvent` 同款拷贝代码:

```kotlin
override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
    if (ev.action == MotionEvent.ACTION_DOWN) {
        val focused = currentFocus
        if (focused is EditText) {
            val outRect = Rect()
            focused.getGlobalVisibleRect(outRect)
            if (!outRect.contains(ev.rawX.toInt(), ev.rawY.toInt())) {
                val imm = getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager
                imm.hideSoftInputFromWindow(binding.root.windowToken, 0)
                focused.clearFocus()
            }
        }
    }
    return super.dispatchTouchEvent(ev)
}
```

## 为什么错

- 每个新页面要重复同一份代码(含 EditText 的所有 Activity 都要写一遍)
- 容易漏(新人新页面忘写)→ 用户报"键盘永远遮挡"持续累积
- 系统默认行为就是"点输入框外不收键盘",用户体验断裂

## ✅ 正确

抽到统一自适应基类,默认开启"点外部收键盘":

```kotlin
abstract class AdaptiveBaseActivity : AppCompatActivity() {

    /** 子类覆写返 false 关闭"点外部收键盘"行为(默认开启) */
    protected open fun dismissKeyboardOnOutsideTap(): Boolean = true

    override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
        if (dismissKeyboardOnOutsideTap() && ev.action == MotionEvent.ACTION_DOWN) {
            val focused = currentFocus
            if (focused is EditText) {
                val outRect = Rect()
                focused.getGlobalVisibleRect(outRect)
                if (!outRect.contains(ev.rawX.toInt(), ev.rawY.toInt())) {
                    val imm = getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager
                    imm.hideSoftInputFromWindow(window.decorView.windowToken, 0)
                    focused.clearFocus()
                }
            }
        }
        return super.dispatchTouchEvent(ev)
    }
}
```

**收益**:所有继承基类的页自动获得行为;极端场景(内嵌 WebView 自有键盘)子类可 override 关闭;已有重复代码可批量删;未来新页零成本。

## lint 状态

- ⏳ Android:含 EditText 的 Activity 若未继承统一基类 → 要求主动加 override;否则 fail
- ⏳ iOS:抽出 `DismissKeyboardOnOutsideTap` ViewModifier 后,`grep TextField` 命中页面应在外层调

**预防**:任何"系统默认行为不友好但全局一致"的交互(键盘收回 / 安全区 / 状态栏 / 返回拦截 / Toast),第一反应抽到统一基类,而非各页自做。两次踩同样坑就够了 — 第三次必须先抽 base class。

关联:0014(SwiftUI 固定区 + 键盘顶整页,同源用户体验问题)。
