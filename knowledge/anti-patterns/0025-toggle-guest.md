---
doc_id: "ap-0025"
container: anti-patterns
platform: cross
summary: "toggle / 偏好类组件对 guest 用户应允许视觉切换，不强行打断主流程"
---

# 0025 — toggle / 偏好类组件对 guest 用户应允许视觉切换，不强行打断主流程

- **平台**:iOS（首踩 + 修）；Android widget 层无内置 guest 拦截，语义上当前合规
- **复发次数**:0
- **lint 状态**:行为决策类，无法静态扫描

## ❌ 错误

guest（未登录）用户 tap 偏好 toggle → 立即 dispatch `.delegate(.requireLogin)` 弹登录：

```swift
case .view(.toggleTapped):
    switch state.userTier {
    case .guest:
        return .send(.delegate(.requireLogin))   // ❌ 直接弹登录，toggle 视觉卡住
    case .free:
        return .send(.delegate(.requireSubscription))
    case .member:
        state.isPreferenceOn.toggle()
        return .send(.delegate(.valueChanged))
    }
```

## 为什么错

- 偏好 toggle 是**用户偏好设置**，guest 想预选作为意向表达，本质上不是安全行为
- 真实权限**由后端在 submit 时校验**（免费 tier 拦截），前端 toggle 视觉切换不会绕过权限
- guest tap → 弹登录 → 用户体验"我点 toggle 怎么变成弹登录" → 主流程被打断 + 困惑
- 同样的偏好（订阅 / 推送通知 / 主题切换 / 字幕开关）若都按 guest = 立即弹登录处理，App 会处处打断

## ✅ 正确

guest 状态视觉切换，提交时由后端校验：

```swift
case .view(.toggleTapped):
    switch state.userTier {
    case .guest:
        state.isPreferenceOn.toggle()                 // ✅ 视觉切换
        return .send(.delegate(.valueChanged))         // ✅ 通知父级 state 变化
        // 真实是否生效 → submit 时由 backend 校验 free tier 拦截
    case .free:
        return .send(.delegate(.requireSubscription)) // ✅ 已登录但订阅缺失，弹订阅页（不打断当前流程）
    case .member:
        state.isPreferenceOn.toggle()
        return .send(.delegate(.valueChanged))
    }
```

guest vs free 行为差异保留理由：
- **guest 走视觉切换**：还没绑定身份，弹登录会打断主流程
- **free 走 requireSubscription**：已登录但订阅缺失，弹订阅页是合理路径

前后端契约要求：guest submit 时 backend 必须**拒绝**受限偏好（同等 free tier 待遇），返回明确 error code → 前端映射到"先弹登录 → 走订阅链路"。

## lint 状态

- iOS: ❌ 行为决策类，无法静态扫描
- Android: N/A（无 guest 拦截路径）

## 通用原则

- **偏好 / 设置类组件**（toggle / select / slider）的 guest 行为 = **视觉切换 + state 落本地**，不打断主流程
- **真实权限校验放服务端 submit 时**，前端只做意向表达
- **登录拦截只在"创作真正提交 / 分享 / 下载"等"消费身份"动作时触发**，不在偏好微交互上触发

典型对应组件：去水印开关 / 字幕开关 / 隐私 Public-Private 切换 / 推送通知开关 / 主题切换 / 任何"用户偏好预选"性质的 toggle / segment / select。
