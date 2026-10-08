---
doc_id: "ap-0112"
container: anti-patterns
platform: android
summary: "childFragmentManager show + parent setFragmentResultListene…"
---

# 0112 — childFragmentManager show + parent setFragmentResultListener 错配

- **平台**:Android(iOS 无 FragmentManager,N/A)
- **复发次数**:0

## ❌ 错误

parent Fragment 用 `.show(childFragmentManager)` 弹出子 sheet,child sheet `setFragmentResult(key, bundle)`(Fragment KTX 扩展)→ 走 child 的 `parentFragmentManager` = parent 的 `childFragmentManager`;parent sheet 用裸 `setFragmentResultListener(key)`(Fragment KTX 扩展)→ 注册在 parent 的 `parentFragmentManager` = Activity 的 supportFragmentManager → **不同 FM 监听不到**。子弹窗常有 Toast "已添加" 等成功提示 → **假成功**,排查时极易误判为"数据层 bug"而非回传链路断。

```kotlin
private fun showWriteYourOwnSheet() {
    ChildSheet().show(childFragmentManager, "child")  // child 在 parent 的 childFM
}
// 却用 Fragment KTX 扩展监听 → 注册在 parentFragmentManager (Activity supportFM)
import androidx.fragment.app.setFragmentResultListener
setFragmentResultListener(Child.KEY_RESULT) { _, bundle ->
    /* 永不触发 — 子弹窗 setFragmentResult 发到 child FM,监听器在 parent FM */
}
```

## 为什么错

`Fragment.setFragmentResult` / `Fragment.setFragmentResultListener` 两个 KTX 扩展都走 `parentFragmentManager`。子弹窗用 parent 的 `childFragmentManager` show 时,其 `setFragmentResult` 发到 parent 的 `childFM`;parent 用裸扩展 `setFragmentResultListener` 注册在自己的 `parentFM`(Activity supportFM)→ 两个 FM 不是同一个 → 监听器永不触发,结果传不回。

## ✅ 正确

```kotlin
// 在子弹窗结果所在的同一 FM(childFragmentManager)上监听
childFragmentManager.setFragmentResultListener(
    Child.KEY_RESULT, viewLifecycleOwner
) { _, bundle -> /* 收到 */ }
```

## 判定线

- 同文件 grep `.show(childFragmentManager,` 出现 + `setFragmentResultListener(` 裸调用(非 `childFragmentManager.setFragmentResultListener`)→ 反模式。

## lint 状态

- ✅ Android 可静态检查:同文件 grep `.show(childFragmentManager,` + 裸 `setFragmentResultListener(` → 报违规。
- ❌ iOS 不适用(非 Fragment 架构)。

## How to apply

- 嵌套 sheet/dialog 回传场景 → parent **必须显式** `childFragmentManager.setFragmentResultListener(...)`,**不可裸调用** Fragment 扩展。
- `/code-review` checklist 加 "嵌套 sheet 回传 FM 一致性" 一条。
- 协调端 task md baseline 触发"运行期 binding / FragmentManager"敏感标识 → 必先派 Dev runtime audit(非静态 grep)。

## 关联

- static grep ≠ runtime 真值。
- 协调端写技术文档凭印象编(同源根因)。
- 不凭印象下发 task master。
