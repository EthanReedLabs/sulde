---
doc_id: "ap-0022"
container: anti-patterns
platform: cross
summary: "登录拦截 delegate 设计了但父 reducer 没接住"
---

# 0022 — 登录拦截 delegate 设计了但父 reducer 没接住

- **平台**:iOS（TCA delegate 链）+ Android（进程级 pending action 对齐）
- **复发次数**:1
- **lint 状态**:Android ✅ 脚本规则；iOS ⏳ TODO

## ❌ 错误（iOS）

子 Feature emit delegate，但父 reducer 没有匹配 case 接住：

```swift
// 某 child Feature
public enum Action {
    case delegate(Delegate)
    public enum Delegate {
        case requireLogin(pendingActionId: String)
    }
}

// 触发时
case .view(.actionTapped(let id)) where !state.isLoggedIn:
    return .send(.delegate(.requireLogin(pendingActionId: id)))

// 但 AppFeature 父 reducer 没有匹配的 case 接住:
.ifLet(\.child, action: \.child) {
    ChildFeature()
}
// ↑ 没有 onChange / 没有 child.delegate 处理 → delegate 落空
```

## 为什么错

- TCA delegate action 是"父子通信契约"，子 emit delegate 但父不处理 = action 落空
- 用户视角：按钮 → 没反应（无登录拦截 + 也没真的执行动作）
- 调试困难：子 reducer 逻辑看起来全对，问题在父级未实现
- Android 同源：走 implicit Intent 不会失败（系统路由），但若改显式 `requireLogin(callback)` 风格，callback 不接听同样会丢动作

## ✅ 正确

```swift
// AppFeature 必须接住所有 child 的 delegate
case .child(.delegate(.requireLogin(let pendingId))):
    state.pendingActionId = pendingId
    state.auth = AuthFeature.State()
    return .none
```

登录成功后 dispatch `completePending*` action 回放被拦截的动作。Android 对应：进程级 pending action 单例 + 登录页 onResume 消费回放。

## lint 状态

- iOS: ⏳ TODO — `grep '\.delegate(\.requireLogin'` 出现的每个 case，必须在 AppFeature 有匹配的接住 case
- Android: ✅ grep 规则扫所有 `startActivity(Intent(ACTION_LOGIN))` 必须改用携带 callback 的 `requireLogin(context, pendingAction)`

## 预防

任何 `delegate(.requireLogin)` / `delegate(.requireXxxx)` 设计完毕后，**必须**在最近的父 reducer 显式补 case 闭环，即使空操作 + TODO 也要有，避免"delegate 看似工作但落空"。

## 关联

- 登录拦截行为契约（登录入口触发场景）
