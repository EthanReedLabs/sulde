---
doc_id: "ap-0217"
container: anti-patterns
platform: android
summary: "Compose 里 bottom sheet 还没关就弹 AlertDialog,出现点不动、点穿、外部点击关错层、输入框抢不到焦点"
related: [ap-0116]
sedimented_by: auto
---

# 0217 — Compose bottom sheet 与 AlertDialog 叠加导致点击/焦点分发不稳定

- **平台**:Android(Compose)
- **复发次数**:1

## ❌ 错误

bottom sheet 里的某个动作要"确认一下",于是**在 sheet 仍处于展开(或正在收起动画)状态时直接把 dialog 的 state 置 true**,让两层弹层同屏叠加:

```kotlin
// ❌ sheet 没关就开 dialog,两层同时在场
ModalBottomSheet(onDismissRequest = { showSheet = false }) {
    SheetContent(
        onDeleteClick = { showConfirmDialog = true }   // sheet 仍然展开
    )
}

if (showConfirmDialog) {
    AlertDialog(
        onDismissRequest = { showConfirmDialog = false },
        /* ... */
    )
}
```

**现象**(不必然每次复现,和机型/动画时机有关):

- dialog 的按钮点不动,或点击穿透到下面的 sheet 内容。
- 点 dialog 外部,关掉的是 sheet 而不是 dialog(或两层一起消失)。
- 返回键只关掉其中一层,另一层残留且失去输入响应。
- dialog 内的 `TextField` 抢不到焦点 / 键盘不弹 / 弹了但输入进了下层。

## 为什么错

- Compose 的 `Dialog`(以及基于它的 `AlertDialog`)和模态 sheet **各自渲染在独立的平台窗口里**,不是同一棵 composition 里的两个普通图层。
- 触摸事件与焦点由**窗口层级**决定归属,而不是由业务代码的 state 顺序决定。两个模态窗口同时在场时,"谁在最上层、谁吃掉 outside touch、谁持有 IME 焦点"取决于窗口创建/销毁的先后与动画时序——业务代码里看不到这条时间线。
- sheet 的收起是**带动画的异步过程**:state 已经变了不代表窗口已经销毁。在这个窗口期里新建 dialog 窗口,层级关系处于中间态。
- 每层模态各自持有一套 scrim + outside-click dismiss + 返回键处理,叠加后这些处理**互相截获**,于是出现"关错层"。

本质:把"两个独立模态窗口"当成"同一页面上的两个条件渲染分支"来建模。

## ✅ 正确

**串行化:先把 sheet 关到位,再开 dialog——同一时刻只允许一个模态窗口在场。**

```kotlin
val scope = rememberCoroutineScope()
val sheetState = rememberModalBottomSheetState()

SheetContent(
    onDeleteClick = {
        scope.launch {
            sheetState.hide()          // 挂起到收起动画真正结束
        }.invokeOnCompletion {
            showSheet = false          // 卸载 sheet 窗口
            showConfirmDialog = true   // 再建 dialog 窗口
        }
    }
)
```

要点:

- 用 sheet 自己提供的**挂起式收起 API + 完成回调**作为边界,不要用固定 `delay(300)` 猜动画时长(动画时长受系统动画缩放、无障碍设置、机型影响)。
- 如果确认结果还要回到 sheet,把它建模成**一个弹层状态机**(`None / Sheet / Dialog`)而不是两个独立 boolean:两个 boolean 天然允许出现"都为 true"的非法态。

```kotlin
sealed interface Overlay {
    data object None : Overlay
    data object Sheet : Overlay
    data class Confirm(val targetId: String) : Overlay
}
```

- 确认关闭后再决定回不回 sheet,由状态机的转移显式表达,避免"关一个开一个"散落在各个回调里。

## 判定线

同一 composable 作用域里出现两个及以上模态弹层 state,且**任一转移路径存在两者同时为 true 的中间态** → 违规。

```bash
# 粗筛:同文件内既有 sheet 又有 dialog 的弹层入口
grep -rln "ModalBottomSheet" --include="*.kt" . | xargs grep -ln "AlertDialog\|Dialog("
```

命中后人工看状态机:是否存在"未 hide 就置 dialog=true"的路径。

## lint 状态

- Android:⏳ 无法静态判定(运行时窗口时序 + 状态机可达性,grep 只能粗筛)。落到 `/code-review` checklist 一条:「模态弹层不得叠加;关一个开一个必须等前者收起完成」。
- iOS:同类风险存在但机制不同(UIKit presentation 栈,present 被静默丢弃),见 ap-0116。

## 关联

- ap-0116(iOS UIKit 链式 sheet present-while-dismissing 竞态)—— **同一族问题的另一平台版本**:都是"关一个开一个没有串行化",但根因不同:iOS 是单 `presentedViewController` 约束下 present 被静默丢弃并导致状态永久卡死;Compose 是多个独立模态窗口共存后输入/焦点分发归属不确定。共同解法都是"用系统给的完成回调做边界,禁止固定 delay"。
