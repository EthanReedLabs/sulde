---
doc_id: "ap-0116"
container: anti-patterns
platform: ios
summary: "iOS UIKit 链式 sheet present-while-dismissing 竞态"
related: [ap-0217, "tech-docs/案例研究/02-iOS-TCA架构实践/UIKit链式模态present-dismiss竞态"]
---

# 0116 — iOS UIKit 链式 sheet present-while-dismissing 竞态

- **平台**:iOS
- **复发次数**:1

## ❌ 错误

一个 modal(如长按 ActionSheet)的某个动作要"关掉自己 + 打开下一个 modal"。脚手架 action handler 先 `action.handler()`(发 TCA action)再 `self.dismiss(animated: true)`,而该 TCA action 经状态观察反应式地在**同一/下一 runloop**调用 `present(下一个 sheet)`。此时上一个 sheet 的 dismiss 动画**尚未走完** → UIKit「同时只能一个 presentation」→ `present` 被**静默丢弃**。

```swift
// 脚手架:点动作先发 action 再 dismiss 自己
{ [weak self] action in
    action.handler()                 // → store.send(.nextSheetTapped) → showNextSheet = true
    self?.dismiss(animated: true)    // 当前 sheet 开始 dismiss(动画中)
}

// 宿主:状态观察里反应式 present 下一个 sheet
if state.showNextSheet && !lastShown {
    lastShown = true
    present(nextHosting, animated: true)   // ← 撞上正在 dismiss 的 sheet,静默失败
}
```

**现象**:下一页不弹;且 `showNextSheet=true` / `targetId=X` / `lastShown=true` 全部卡死(下一页从没真正 present,dismiss 回调永不触发,无人复位)→ 边沿触发(`targetId != last`)再也不满足 → **该入口再也不弹**。

## 为什么错

- UIKit 一个 VC 同时只能有一个 `presentedViewController`;在 dismiss 动画进行中调 `present` 被丢弃,**且不报错不抛异常**(静默)。
- 反应式 present(由 state 观察驱动)与脚手架的 self-dismiss 在时间上解耦,开发者看不到"同一时刻两个事务"。
- present 失败后状态没有任何回滚路径 → 一次失败永久卡死后续交互。

## ✅ 正确

present 下一个 sheet 前,**等上一个 sheet 的 dismiss 动画走完**(用 `transitionCoordinator` 完成回调):

```swift
private func showNextSheet(id: String) {
    if let presented = presentedViewController {
        if let coordinator = presented.transitionCoordinator {
            coordinator.animate(alongsideTransition: nil) { [weak self] _ in
                self?.presentNext(id: id)   // dismiss 动画结束后再 present
            }
        } else {
            presented.dismiss(animated: true) { [weak self] in
                self?.presentNext(id: id)
            }
        }
    } else {
        presentNext(id: id)
    }
}
```

## lint 状态

- iOS ❌ 无法静态检查(运行时 present/dismiss 时序,grep 不住)。靠 `/code-review` checklist 加一条:「链式 sheet(关一个开一个)必须等前者 dismiss 完成再 present,禁止反应式 present 与 self-dismiss 同 runloop」。
- Android ⏳ 待核查(DialogFragment 机制不同,大概率 N/A)。

## How to apply

- 链式 sheet 入口(关一个开一个的 UGC / 分享 / 举报等)封装 `presentAfterDismiss(_:)` 守卫(scaffold 级抽到公共 UIKit 扩展)。
- 同款风险点 sweep:其他页若有"关一个 sheet 开另一个"的链式入口,同样隐患;派 grep sweep(`present(` 调用方 + 反应式 present)。

## 关联

- 后续重写时严格保留 race 守卫逐字不动。
- 审计强制第二轮自问同源风险点 sweep。
