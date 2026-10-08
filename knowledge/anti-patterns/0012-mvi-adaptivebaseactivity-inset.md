---
doc_id: "ap-0012"
container: anti-patterns
platform: android
summary: "MVI 基类不继承统一自适应基类 → 每个二级页重复补状态栏手动 inset"
---

# 0012 — MVI 基类不继承统一自适应基类 → 每个二级页重复补状态栏手动 inset

- **平台**:Android(iOS 需对称核查等价基类)
- **复发次数**:≥ 3(多个 MviActivity 子类均踩过)

## ❌ 错误

```kotlin
// MviActivity.kt
abstract class MviActivity<S, VB> : AppCompatActivity() {   // ← 没继承统一自适应基类
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(binding.root)                         // ← 不走自适应基类的 setContentView
    }
}

// 于是每个子类不得不自己打补丁:
class XxxActivity : MviActivity<...>() {
    override fun onCreate(...) {
        super.onCreate(savedInstanceState)
        AdaptiveLayout.init(this)                            // ← 补丁 1
        AdaptiveLayout.applyStatusBar(binding.root)          // ← 补丁 2
        centerTopBarTitle()                                  // ← 补丁 3(runtime LayoutParams hack)
    }
}
class YyyActivity : MviActivity<...>() {
    override fun onCreate(...) {
        super.onCreate(savedInstanceState)
        binding.topBar.fitStatusBar()                        // ← 另一种形态的补丁,语义还不一致
    }
}
```

## 为什么错

- 多个子类手动补丁语义不一致(`applyStatusBar` vs `fitStatusBar`)→ topBar 间距每页不同
- 手动补丁在未初始化 edge-to-edge 的 window 上不稳定(insets listener 返回 0)
- 新增子类的 dev 若不读所有同类,必忘某处补丁 → 状态栏贴死重现(见 0008 三层根因)
- 和 0001"在每个页面单独修系统级问题"同源,但 0001 是泛化原则,本条是 MVI 基类具体落地缺失

## ✅ 正确

```kotlin
// MviActivity.kt
abstract class MviActivity<S, VB> : AdaptiveBaseActivity() {  // ← 继承统一自适应基类
    // setContentView override 自动给 contentView 根挂 statusBar inset listener
    // 默认 FitConfig(statusBar=true);子类按需 override fitConfig()
}

// 子类干净,无补丁
class XxxActivity : MviActivity<...>() {
    override fun onCreate(...) {
        super.onCreate(savedInstanceState)
        // 不再需要 init / applyStatusBar / fitStatusBar
    }
}
// title 居中改走 XML 声明式(配合 AppTopBar.titleGravity 属性),不用 runtime hack
```

## lint 状态

- ⏳ Android:lint 规则
  - 规则 A:MviActivity 基类必须继承统一自适应基类
  - 规则 B:MviActivity 子类禁止手动调 `fitStatusBar` / `AdaptiveLayout.applyStatusBar`
- iOS:需对称核查等价基类(MviViewController / AdaptiveScaffold)是否有同类问题,有则派独立任务
- 人工 review:新增 MVI Activity PR 必经

关联:0001(同源原则)、0008(本条是其根因之一)。
