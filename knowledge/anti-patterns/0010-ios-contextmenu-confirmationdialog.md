---
doc_id: "ap-0010"
container: anti-patterns
platform: ios
summary: "iOS 长按菜单用 `.contextMenu` 而不是 `.confirmationDialog`"
---

# 0010 — iOS 长按菜单用 `.contextMenu` 而不是 `.confirmationDialog`

- **平台**:iOS(Android 无 `.contextMenu` API,见末"Android 语义镜像")
- **复发次数**:1

## ❌ 错误

```swift
card(item)
    .contextMenu {
        Button { store.send(.view(.renameTapped(id: item.id))) } label: {
            Label("Rename", systemImage: "pencil")
        }
        Button(role: .destructive) {
            store.send(.view(.deleteTapped(id: item.id)))
        } label: {
            Label("Delete", systemImage: "trash")
        }
    }
```

## 为什么错

- UI 行为契约规定长按菜单必须用 `.confirmationDialog(titleVisibility:.visible)`,视觉等效底部弹层(BottomSheet),对齐 Android `BottomSheetDialogFragment`
- `.contextMenu` 是 iOS 上下文菜单(悬浮卡片式),视觉与 Android 差异大 → 两端交互体验不一致
- SwiftUI dev 习惯性用 `.contextMenu`(Apple HIG 列表惯用模式),但"两端一致性优先"项目里显式禁用

## ✅ 正确

```swift
@State private var longPressTargetId: String?

card(item)
    .onTapGesture { store.send(.view(.itemTapped(id: item.id))) }
    .onLongPressGesture(minimumDuration: 0.5) {
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        longPressTargetId = item.id
    }

// body 根部挂 confirmationDialog(等效 BottomSheet)
.confirmationDialog(
    longPressTargetItem?.title ?? "",
    isPresented: .init(
        get: { longPressTargetId != nil },
        set: { if !$0 { longPressTargetId = nil } }
    ),
    titleVisibility: .visible
) {
    if let id = longPressTargetId {
        Button("Rename") { store.send(.view(.renameTapped(id: id))); longPressTargetId = nil }
        Button("Delete", role: .destructive) { store.send(.view(.deleteTapped(id: id))); longPressTargetId = nil }
        Button("Cancel", role: .cancel) { longPressTargetId = nil }
    }
}
```

## Android 语义镜像

Android 无 `.contextMenu` API,但对应反模式是"长按菜单用 `PopupMenu` / `ActionMode` 替代 `BottomSheetDialogFragment`"。两端一致性要求长按菜单统一走底部弹层。

## lint 状态

- ✅ iOS:grep `^\s*\.contextMenu\s*[({]` 命中即 fail
- ⏳ Android:检查 `PopupMenu.show` / `ActionMode` 在长按场景的误用
- 人工 review:`/code-review` checklist 加"grep 新建 View 是否有 `.contextMenu` / `PopupMenu.show`"
