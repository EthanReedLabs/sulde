---
doc_id: "tech-docs/案例研究/02-iOS-TCA架构实践/UIKit链式模态present-dismiss竞态"
container: case-studies
platform: none
summary: "**技术域**：iOS 架构 / UIKit / SwiftUI Hosting / TCA 状态驱动 UI **难度…"
related: [ap-0116]
---

# UIKit 链式模态 Present/Dismiss 竞态案例研究

> **技术域**：iOS 架构 / UIKit / SwiftUI Hosting / TCA 状态驱动 UI
> **难度**：⭐⭐⭐⭐⭐
> **关键词**：UIKit modal / present / dismiss / transitionCoordinator / presentedViewController / TCA / reactive presentation / bottom sheet / 状态卡死 / runloop 竞态
> **可迁移场景**：链式 sheet、ActionSheet 后打开二级弹窗、举报/分享/编辑流程、TCA state 观察驱动 UIKit present、SwiftUI + UIKit 混合模态

---

## 场景与系统架构

某 iOS 页面有一个长按菜单。用户长按卡片后，页面弹出一个 action sheet；点击其中某个动作后，当前 sheet 关闭，同时应打开下一个 sheet，例如原因选择页、二次确认页或表单页。

业务层采用 TCA 管理状态，UIKit 负责实际 modal presentation。整体模型是：

1. sheet 内按钮触发 action handler。
2. action handler 向 TCA `Store` 发送 action。
3. reducer 更新状态，例如 `showNextSheet = true`。
4. 页面观察状态变化，反应式调用 `present(...)`。
5. 当前 sheet 自己执行 `dismiss(animated: true)`。

这个模型的风险在于：状态变化和 UIKit 转场不是同一个事务。TCA state 可以在同一轮 runloop 或下一轮 runloop 里立刻变成“应该展示下一个 sheet”，但 UIKit 上一个 sheet 的 dismiss 动画可能还没结束。

### UIKit Modal Presentation 模型

UIKit 的 modal presentation 有一个重要约束：一个 presenting view controller 在同一时间只能稳定管理一个 `presentedViewController`。当上一个 modal 正在 dismiss 动画中时，presentation 栈仍处于 transition 过程；此时再调用 `present`，并不等价于排队等待。

```
HostViewController
├── presentedViewController = ActionSheet
│
├── 用户点击 ActionSheet 内按钮
│   ├── TCA store.send(.nextSheetTapped)
│   └── ActionSheet.dismiss(animated: true)
│
├── dismiss transition 进行中
│   └── HostViewController 仍处于 modal transition 状态
│
└── 状态观察触发 present(NextSheet)
    └── 与 dismiss transition 撞车，present 可能被 UIKit 静默丢弃
```

### TCA 反应式 Present 链路

```
ActionSheet button
└── action.handler()
    └── store.send(.openNextSheet(id))
        └── reducer:
            ├── state.nextSheetTargetId = id
            └── state.showNextSheet = true
                │
                ▼
ViewController observe state
└── if showNextSheet && edgeTriggerSatisfied {
        markPresented()
        present(nextSheet, animated: true)
    }

ActionSheet 封装层
└── dismiss(animated: true)
```

问题发生在最后两条链路：反应式 present 和当前 sheet 的自关闭在时间上解耦，但运行时可能撞在同一个 modal transition 窗口里。

---

## 问题现象

用户操作路径：

1. 长按某个卡片。
2. 第一个 action sheet 正常弹出。
3. 点击其中的动作，例如“举报”。
4. 第一个 sheet 关闭。
5. 预期第二个 sheet 弹出，但实际没有弹出。
6. 此后再次长按同一卡片或其他卡片，长按菜单也不再弹出。

这不是单次 present 失败那么简单。真正严重的是：第二个 sheet 没有展示，但 TCA 状态已经进入“已请求展示 / 已标记展示”的状态，后续边沿触发条件不再满足，导致入口永久卡死。

可观测状态可以抽象为：

| 状态 | 预期 | 实际 |
|---|---|---|
| `showNextSheet` | 第二个 sheet 展示后，关闭时复位 | 被置为 true，但 sheet 从未真正展示 |
| `targetId` | 记录当前操作对象，流程结束后清空 | 保留旧 id |
| `lastPresentedId` / edge marker | 防止重复 present，同一次展示后更新 | 已更新为旧 id |
| dismiss 回调 | 第二个 sheet 关闭后触发状态回滚 | 因为第二个 sheet 从未出现，回调永远不触发 |

结果是：业务状态认为“已经展示过”，UIKit 实际没有展示；二者永久分叉。

---

## 根因分析

### 根因一：dismiss 动画进行中调用 `present`，UIKit 可能静默丢弃

UIKit 的 `present(_:animated:)` 和 `dismiss(animated:)` 都是异步转场。调用 `dismiss(animated: true)` 后，并不代表 modal 立刻从 presentation 栈中消失；它会进入一段 transition。直到动画完成，`presentedViewController` 和内部 presentation 状态才稳定。

有缺陷的链式调用可以简化为：

```swift
// 第一个 sheet 内的 action handler
{ [weak self] action in
    action.handler()                 // 触发 TCA action：showNextSheet = true
    self?.dismiss(animated: true)     // 当前 sheet 开始 dismiss 动画
}
```

页面观察状态后立刻 present：

```swift
func observeState(_ state: ViewState) {
    if state.showNextSheet && state.targetId != lastPresentedId {
        lastPresentedId = state.targetId
        present(nextSheetController, animated: true)  // ❌ 可能撞上 dismiss transition
    }
}
```

当 `present` 发生在上一个 sheet dismiss 动画期间，UIKit 可能不会抛异常，也不会给业务层一个明确失败回调。表现就是：代码执行了，第二个 sheet 没出现。

平台机制层面的关键点是：UIKit modal transition 是有状态的，不是一个普通函数调用队列。`dismiss` 开始和 `dismiss` 完成之间存在窗口期；在这个窗口内发起新的 `present`，行为不应被当作可靠。

### 根因二：反应式 present 与 self-dismiss 在同一 runloop 撞车

TCA 的优势是 state 驱动 UI，但它不自动理解 UIKit 的 transition 生命周期。下面两个动作在代码结构上看似独立：

```
业务动作：store.send(.openNextSheet)
UI 动作：当前 sheet dismiss(animated: true)
```

实际时序可能是：

```
t0  用户点击第一个 sheet 内按钮
t0  action.handler() 发送 TCA action
t0  reducer 设置 showNextSheet = true
t0  状态观察触发 host.present(nextSheet)
t0  当前 sheet 调用 self.dismiss(animated: true)
或
t0  self.dismiss(animated: true) 先开始 transition
t0+ 状态观察触发 host.present(nextSheet)
```

无论先后差几十毫秒，问题本质相同：下一个 `present` 没有等待上一个 modal 的 transition 完成。

这类竞态很隐蔽，因为业务代码里没有显式写“同时 present 和 dismiss”。它由两个框架组合产生：TCA 让 present 变成状态观察副作用，sheet 封装层又在按钮处理后自我关闭。

### 根因三：present 失败没有状态回滚路径

更深层问题不是 UIKit 静默丢弃一次 present，而是业务状态提前标记了“已经 present”。典型写法是为了避免重复 present：

```swift
if state.showNextSheet && state.targetId != lastPresentedId {
    lastPresentedId = state.targetId      // ❌ 在确认 present 成功前更新 marker
    present(nextSheetController, animated: true)
}
```

如果 `present` 成功，后续第二个 sheet 关闭时会发出 dismissed action，清理 `showNextSheet`、`targetId` 和 marker。可一旦 `present` 被 UIKit 丢弃，第二个 sheet 根本不存在，关闭回调不会发生：

```
showNextSheet = true
targetId = X
lastPresentedId = X
present 被丢弃
└── 没有 presented VC
    └── 没有 dismiss
        └── 没有 dismissed action
            └── 状态永远卡在 true / X / X
```

后续再次长按时，边沿触发条件例如 `targetId != lastPresentedId` 不再满足；即使满足，`showNextSheet` 仍然是旧 true，也可能被观察逻辑当作已处理状态。于是用户看到“长按菜单永久不弹”。

### 根因四：封装的 present 方法隐藏了 transition 边界

很多项目会封装 bottom sheet present 方法，让业务方只调用“展示某个 sheet”。这能减少重复代码，但也容易隐藏 UIKit 的转场约束。业务方以为自己只是设置状态，封装层以为自己只是 dismiss 自身；没有一个地方显式表达“链式 sheet 必须等前一个 dismiss 完成”。

因此，链式 modal 不应只看“谁调用了 present”，还要看“当前是否有 presentedViewController，且它是否正在 transition”。

---

## 解决方案

### 方案一：在 dismiss 完成后再 present 下一个 sheet

核心修复是：如果当前 host 还有 `presentedViewController`，先等它完成 dismiss，再调用下一个 `present`。

```swift
private func showNextSheet(targetId: String) {
    if let presented = presentedViewController {
        if let coordinator = presented.transitionCoordinator {
            coordinator.animate(alongsideTransition: nil) { [weak self] _ in
                self?.presentNextSheet(targetId: targetId)
            }
        } else {
            presented.dismiss(animated: true) { [weak self] in
                self?.presentNextSheet(targetId: targetId)
            }
        }
    } else {
        presentNextSheet(targetId: targetId)
    }
}
```

实际 present 被收敛到一个方法里：

```swift
private func presentNextSheet(targetId: String) {
    let controller = makeNextSheetController(targetId: targetId)
    present(controller, animated: true)
}
```

这段逻辑处理了三种情况：

| 当前状态 | 处理 |
|---|---|
| 没有 `presentedViewController` | 直接 present |
| 有 modal 正在 transition | 通过 `transitionCoordinator` 等 transition 结束 |
| 有 modal 但拿不到 coordinator | 主动 dismiss，并在 completion 中 present |

### 方案二：状态 marker 尽量在真实展示后推进

如果业务层需要 `lastPresentedId` 这类边沿 marker，应尽量在确认 present 已进入稳定状态后推进，或至少在 present 路径失败时有回滚 action。UIKit 没有提供所有失败场景的显式 error，因此更实际的方案是避免在不稳定 transition 窗口调用 present。

可以把状态观察逻辑改成只负责“请求展示”，具体展示时机由 modal coordinator 管理：

```swift
func observeState(_ state: ViewState) {
    guard state.showNextSheet, let targetId = state.targetId else { return }
    modalCoordinator.presentAfterCurrentDismiss(targetId: targetId)
}
```

这样 TCA state 表达业务意图，UIKit coordinator 负责时序落地，二者职责更清晰。

### 为什么用 `transitionCoordinator` / dismiss completion，而不是 delay

**不选择固定 `asyncAfter`**：dismiss 动画时长可能受系统设置、交互式转场、设备性能、Reduce Motion、present style 影响。固定 200ms 或 300ms 只是猜测，既可能太短继续撞车，也可能太长增加等待。

**不选择下一轮 runloop 再 present**：`DispatchQueue.main.async` 只保证推迟到后续任务，不保证 dismiss transition 已完成。modal 动画通常跨多帧，下一轮 runloop 仍可能处于 transition 中。

**不选择只判断 `presentedViewController == nil`**：在 transition 过程中，该属性和内部 presentation 状态可能还没稳定。更可靠的是使用 transition completion 或 dismiss completion 作为边界。

**不选择让第二个 sheet 自己重试 present**：重试会让 modal 时序变得不可预测，也可能造成重复展示。正确做法是把链式展示串成明确的 transition 序列。

### 修复后的时序

```
用户点击第一个 sheet 动作
└── TCA state: showNextSheet = true
    └── host 准备展示第二个 sheet
        ├── 检查当前 presentedViewController
        ├── 等当前 dismiss transition 完成
        └── present(nextSheet)
            └── 第二个 sheet 真正展示
                └── 关闭后发 dismissed action，状态复位
```

用户路径恢复为：

```
长按 -> 第一个 sheet -> 点击动作 -> 第一个 sheet 关闭 -> 第二个 sheet 弹出
关闭第二个 sheet -> 再次长按 -> 第一个 sheet 可重复弹出
```

---

## 可迁移原则

### 1. 链式 modal 必须显式串行化 transition

“关一个再开一个”不能依赖 runloop 运气。UIKit modal transition 要用 `transitionCoordinator` 或 dismiss completion 明确串行化。只要有链式 sheet、二级弹窗、确认页、表单页，都应检查这个约束。

### 2. 状态驱动 UI 不等于可以忽略 UIKit 生命周期

TCA state 可以表达“应该展示”，但 UIKit 决定“什么时候能展示”。反应式 present 必须尊重 `presentedViewController`、dismiss 动画和 transition 状态。

### 3. Present 失败必须有状态回滚设计

如果展示动作会修改 marker、防重状态或目标 id，就要考虑 present 未发生时如何恢复。更好的做法是把 marker 推进放到稳定展示之后，或由 modal coordinator 保证不会在非法窗口调用 present。

### 4. 不要用固定 delay 代替 transition completion

延迟是时间猜测，completion 是生命周期事实。涉及动画、dismiss、interactive transition 时，应优先使用系统回调，而不是 `asyncAfter`。

### 5. 封装层要暴露链式展示能力

如果项目有统一 bottom sheet 封装层，最好提供“当前 modal dismiss 完成后再 present”的能力，而不是让每个业务入口自行处理。链式 modal 是框架能力，不应散落在业务代码里。

---

## 技术深问 Q&A

### Q1：为什么 UIKit 没有直接报错？

UIKit 的 modal transition 很多失败场景不是 Swift error，也不一定抛异常。调用 `present` 时如果 presentation 栈处于不稳定状态，系统可能只打印运行时 warning，甚至表现为静默不展示。业务层不能依赖异常来发现这类问题。

### Q2：`presentedViewController` 不为 nil 就一定不能 present 吗？

通常表示当前 host 已经有 modal。是否能立即 present 取决于当前 presentation 状态。链式 sheet 场景下，应先完成当前 modal 的 dismiss，再 present 下一个。不要在 dismiss transition 中抢先 present。

### Q3：`transitionCoordinator` 的作用是什么？

它描述当前 view controller transition，并允许注册动画同步或完成回调。这里用它不是为了做动画，而是为了拿到“当前 dismiss transition 已结束”的生命周期边界。

### Q4：为什么 `DispatchQueue.main.async` 不够？

它只推迟到主队列的后续任务，不保证动画完成。dismiss 动画可能持续多帧，下一轮 runloop 仍处于 transition 中。completion 回调才是可靠边界。

### Q5：TCA 中应该把 present 放在 reducer 里吗？

不应该。reducer 应保持纯状态转换，表达“需要展示某个 modal”的状态或 action。UIKit present 是副作用，应由 ViewController / coordinator 观察状态后执行，并处理 UIKit 生命周期约束。

### Q6：为什么第二个 sheet 没弹会导致第一个 sheet 以后也不弹？

因为业务状态已经被推进到“第二个 sheet 已请求或已展示”的边沿状态，但真实 UIKit 展示失败，关闭回调不会触发，状态无法复位。后续长按被旧 marker 或旧 target 拦住，于是入口看起来永久失效。
