---
doc_id: "ap-0021"
container: anti-patterns
platform: cross
summary: "Fragment 绕过统一返回钩子(AdaptiveBaseFragment.onBackPressed）"
---

# 0021 — Fragment 绕过统一返回钩子(AdaptiveBaseFragment.onBackPressed）

- **平台**:Android + iOS（对称契约）
- **lint 状态**:Android ✅ 脚本规则；iOS 架构级规避 + 人工 review

## ❌ 错误

Fragment / Feature View 各自直接操作返回拦截，绕过基类统一钩子：

```kotlin
// Android Fragment 里直接操作宿主 Activity 的 back dispatcher
class EditProfileFragment : Fragment() {
    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        requireActivity().onBackPressedDispatcher.addCallback(viewLifecycleOwner) {
            if (hasUnsavedChanges) showDiscardDialog()
            else isEnabled = false.also { requireActivity().onBackPressed() }
        }
    }
}
```

```swift
// iOS Feature View 绕过 modifier，直调 UIKit 或 @Environment(\.dismiss)
struct EditProfileView: View {
    @Environment(\.dismiss) var dismiss  // ❌
    var body: some View {
        content.navigationBarBackButtonHidden().toolbar { ... Button { dismiss() } }
    }
}
```

## 为什么错

- 拦截语义散落，N 个 Fragment 各自实现一套，基类改不动
- 手势返回 vs 按钮返回 vs 系统 back 三路径行为不一致
- 未保存状态的 Discard Dialog 逻辑在各页重复
- 混用 `onBackPressed()` 和 `onBackPressedDispatcher.addCallback` 可能触发嵌套循环

## ✅ 正确

```kotlin
// Android：继承基类 AdaptiveBaseFragment，覆写 onBackPressed
class EditProfileFragment : AdaptiveBaseFragment() {
    override fun onBackPressed(): BackResult {
        if (!hasUnsavedChanges) return BackResult.PROCEED
        ConfirmDialog.show(
            context = requireContext(),
            title = "放弃修改？",
            onConfirm = { requireActivity().finish() },
        )
        return BackResult.HANDLED
    }
}
```

```swift
// iOS：统一 .onBackNavigation modifier
struct EditProfileView: View {
    var body: some View {
        content.onBackNavigation {
            if hasUnsavedChanges {
                store.send(.view(.confirmDiscardTapped))
                return .handled
            }
            return .proceed
        }
    }
}
```

双端语义一一对齐（`BackResult.HANDLED` ↔ `.handled` / `.PROCEED` ↔ `.proceed`）。

## lint 状态

- Android: ✅ grep 规则扫 `feature-*/` 和 `core-ui/widgets/` 下的 `*Fragment.kt`，命中 `requireActivity().onBackPressed()` / `requireActivity().onBackPressedDispatcher.addCallback` 报违规
- iOS: ✅ 架构级规避（`.onBackNavigation` modifier + AdaptiveNavigationController 激活 + Feature View 全走合约）。Swift 动态接入难静态扫描，人工 review 即可

## 关联

- scaffold-map / 框架脚手架规范 Back Handling 段
