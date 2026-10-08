---
doc_id: "tech-docs/案例研究/02-iOS-TCA架构实践/TCA状态机登出登录闭环"
container: case-studies
platform: none
summary: "**技术域**：iOS 架构 / Swift / SwiftUI / The Composable Architect…"
---

# TCA 状态机登出登录闭环案例研究

> **技术域**：iOS 架构 / Swift / SwiftUI / The Composable Architecture
> **难度**：⭐⭐⭐⭐
> **关键词**：TCA / SwiftUI / Store / fullScreenCover / 状态驱动导航 / 登录态 / 登出闭环 / UIKit Representable / selectedTab / 状态机
> **可迁移场景**：登录/登出闭环、401 重新登录、跨 Tab 鉴权、SwiftUI + UIKit 混合导航、TCA 父子状态同步

---

## 场景与系统架构

某 iOS 应用使用 SwiftUI + TCA 管理全局登录态、页面状态和 Tab 导航。用户在个人页或设置页触发登出后，系统需要完成一条完整闭环：调用后端登出、清理本地会话、关闭当前子页面、切回安全 Tab、在再次进入受保护页面时弹出登录页；登录成功后，需要关闭登录弹窗、写入当前用户、恢复待访问页面。

这类流程不是一个接口调用，而是一条跨 Feature、SwiftUI modal、全局 App 状态和 UIKit Tab 宿主的状态机链路。只修其中一段，用户仍可能看到“未登录但不弹登录页”“登录成功但页面空数据”“底栏被 modal 遮挡”“Tab 选中态错乱”等现象。

### TCA 状态机 / 登录登出状态流图

```
RootFeature.State
├── selectedTab: Tab
├── auth: LoginFeature.State?                // fullScreenCover 登录页
├── pendingTabAfterAuth: Tab?                // 登录后要恢复的目标 Tab
└── account: AccountFeature.State
    ├── isLoggedIn: Bool
    ├── currentUser: User?
    └── settings: SettingsFeature.State?     // fullScreenCover 设置页

SwiftUI Root View
├── fullScreenCover(item: store.auth)         // 登录弹窗
├── AccountView
│   └── fullScreenCover(item: settings)       // 设置页
└── UIKit Tab Host
    └── TabBarControllerRepresentable
        └── selectedIndex <-> selectedTab
```

完整闭环应该是：

```
登出触发
└── backend logout（尽力而为）
    └── 本地 session 清理
        └── account.isLoggedIn = false / currentUser = nil
            └── settings = nil，关闭设置页 fullScreenCover
                └── selectedTab 切回安全 Tab
                    └── 访问受保护 Tab 时 auth != nil
                        └── fullScreenCover 展示登录页
                            └── loginCompleted(user)
                                └── auth = nil + currentUser = user + 恢复 pendingTab
```

故障的本质是这条链路里有多个断点，每个断点单独看都只是局部遗漏，但组合起来导致登录态状态机无法闭环。

---

## 问题现象

用户侧可见问题集中在四类：

1. 登出后再次点击个人页，不弹登录页。
2. 在设置页内登出后，设置页的 `fullScreenCover` 仍然覆盖在界面上，底栏不可见或不可操作。
3. 登录成功后，个人页仍显示空数据，体验上等同未登录。
4. 登出/登录切换后，底层 Tab 状态和全局 `selectedTab` 不一致，控制器仍停留在旧 index。

这些现象有一个共同特征：单个 action 已经触发，但下游状态没有同步推进。换句话说，问题不在“用户没有点到按钮”，而在 TCA 状态机的后续节点没有连起来。

从状态链路看，异常表现可以映射为：

| 可观测表现 | 对应断点 |
|---|---|
| 登出后不弹登录页 | 本地登录态没有被清掉，受保护 Tab 的登录守卫不触发 |
| 设置页遮挡底栏 | 子页面状态仍非 nil，`fullScreenCover` 继续展示 |
| 登录成功后页面空数据 | `loginCompleted` 关闭弹窗，但没有同步写入当前用户 |
| Tab index stale | SwiftUI `selectedTab` 已变，但 UIKit controller 未执行同步 |

---

## 根因分析

### 根因一：后端登出失败阻断本地清理

登出动作的旧逻辑把“后端登出成功”和“本地清 session”绑定成强依赖：

```swift
case .view(.logoutTapped):
    return .run { send in
        do {
            try await authClient.logout()
            await send(.result(.logoutSucceeded))
        } catch {
            await send(.result(.loadFailed(message)))  // ❌ 后端失败阻断本地登出
        }
    }
```

素材中的实际触发条件是：登出接口返回格式不符合客户端解码预期，导致 `DecodingError`。虽然用户已经明确选择登出，但 reducer 进入 `loadFailed`，没有继续发送 `.logoutSucceeded`。于是本地 session 没有清理，`profile.isLoggedIn` 仍然保持 true。

在 TCA 状态机里，这会连锁影响导航守卫：

```
logoutTapped
└── authClient.logout() 抛错
    └── send(loadFailed)
        └── 未清本地 session
            └── account.isLoggedIn 仍为 true
                └── 点击受保护 Tab 时守卫认为已登录
                    └── auth 仍为 nil，登录 fullScreenCover 不出现
```

平台/架构层面的关键点是：登录态本地清理是客户端安全状态转换，不应被一个 best-effort 的后端通知接口阻断。后端 token 可以过期失效，客户端 UI 状态必须立即进入已登出态，否则会出现“服务端可能已失效，本地仍认为登录”的不一致。

### 根因二：状态驱动导航中，modal 是否展示完全由可选状态决定

SwiftUI 的 `fullScreenCover(item:)` 或等价状态驱动导航，本质上是把“是否展示页面”绑定到某个可选状态：

```swift
fullScreenCover(item: $store.scope(state: \.settings, action: \.settings)) {
    SettingsView(store: $0)
}
```

只要 `settings` 仍然非 nil，SwiftUI 就会继续展示设置页。用户从设置页内部触发登出时，如果 reducer 只清 session、不清子页面状态，设置页 modal 不会自动消失。

旧状态机缺口是：

```
SettingsView.logoutTapped
└── logoutSucceeded
    ├── 清 session
    └── settings 仍非 nil      // ❌ fullScreenCover 继续展示
```

这类问题常见于 TCA 父子状态：子 Feature 内触发了全局状态变化，但父状态中承载导航的 optional child state 没有同步置空。SwiftUI 不知道“登出意味着关闭设置页”，它只知道绑定的 item 还存在。

### 根因三：`loginCompleted` 关闭了登录页，但没有补齐用户状态

登录成功 action 的旧逻辑只关闭登录弹窗，并处理 pending tab：

```swift
case .auth(.presented(.delegate(.loginCompleted))):
    state.auth = nil
    if let pending = state.pendingTabAfterAuth {
        // 恢复目标 Tab
    }
```

缺口在于：登录完成时已经拿到了用户信息，但没有同步写入个人页状态。素材中的会话存储链路还有一个细节：`setAccessToken` 单独路径不更新 user 字段，导致依赖会话快照异步回填时，`snapshot.user` 仍可能是 nil。

于是状态机变成：

```
loginCompleted(user)
├── auth = nil，登录页关闭
├── pendingTab 恢复
└── account.currentUser 未写入       // ❌ 页面仍按空用户渲染
```

TCA 里 delegate action 通常是父 Feature 获得子 Feature 结果的边界。既然 `loginCompleted` 已经携带了 user，父状态机就应该在这个同步边界上写入关键状态，而不是完全依赖另一个异步 stream 稍后补齐。否则 UI 会短暂或永久处在“已关闭登录页，但用户数据为空”的中间态。

### 根因四：SwiftUI 状态变了，但 UIKit Representable 没有实现同步

应用底栏由 UIKit Tab 控制器承载，通过 SwiftUI Representable 嵌入。旧实现中，SwiftUI 只传入了 store，没有显式传入当前选中 Tab，`updateUIViewController` 也是空实现或没有真正同步：

```swift
private var tabBarHost: some View {
    TabBarControllerRepresentable(store: store)
}

func updateUIViewController(
    _ uiViewController: TabBarController,
    context: Context
) {
    // ❌ 没有把 SwiftUI/TCA selectedTab 同步到 UIKit selectedIndex
}
```

SwiftUI 与 UIKit 混合时，Representable 的更新机制很明确：当传入参数变化时，SwiftUI 会调用 `updateUIViewController`，由开发者把新状态应用到 UIKit 对象。UIKit 控制器不会自动观察 TCA Store，也不会自动知道 `selectedTab` 已经变成 `.home`。

因此登出流程中即使全局状态已经切回安全 Tab，底层 controller 仍可能停在旧的 `selectedIndex`：

```
state.selectedTab = .home
└── SwiftUI body 重新计算
    └── Representable 参数没有 selectedTab
        └── updateUIViewController 不同步
            └── TabBarController.selectedIndex 仍指向旧 Tab
```

这是典型的跨 UI 框架状态桥接缺口：TCA 状态机已经推进，但 UIKit 宿主没有被喂入新的状态。

---

## 解决方案

### 修复一：登出采用客户端必达语义

后端登出可以失败、超时或返回非标准格式，但本地登出必须继续完成。修复后，后端错误只记录，不阻断 `.logoutSucceeded`：

```swift
case .view(.logoutTapped):
    return .run { send in
        do {
            try await authClient.logout()
        } catch {
            NSLog("[Logout] backend failed, ignored: \(error)")
        }

        await send(.result(.logoutSucceeded))  // ✅ 本地清理必达
    }
```

这样状态机语义变成：

```
用户点击登出
├── 尝试通知后端
└── 无论后端结果如何，都进入本地 logoutSucceeded
```

为什么这样修：登出按钮代表用户希望客户端立即退出当前身份。后端接口属于清理远端状态的 best-effort 步骤，不能反过来决定本地 UI 是否退出登录。

### 修复二：登出成功时同步关闭子页面状态

在 `.logoutSucceeded` reducer 中，除清理 session 和用户态外，同时清掉设置页 optional state：

```swift
case .result(.logoutSucceeded):
    state.isLoggedIn = false
    state.currentUser = nil
    state.settings = nil              // ✅ 驱动 fullScreenCover 关闭
    return .none
```

为什么这样修：`fullScreenCover` 是状态驱动导航，关闭 modal 的正确方式就是把对应状态置为 nil。手动 dismiss 或从 View 层绕过状态机会制造 View 与 Store 不一致。

### 修复三：`loginCompleted` 同步写入当前用户

登录完成 delegate action 携带用户信息时，父状态机应立即写入个人页状态：

```swift
case .auth(.presented(.delegate(.loginCompleted(let user)))):
    state.auth = nil
    state.account.currentUser = user   // ✅ 闭合登录成功后的页面数据链

    if let pending = state.pendingTabAfterAuth {
        state.selectedTab = pending
        state.pendingTabAfterAuth = nil
    }
    return .none
```

为什么这样修：`loginCompleted(user)` 是同步、确定的状态边界；会话流可以继续作为后续一致性来源，但不能成为登录页关闭后页面是否有用户数据的唯一依赖。这样能避免“登录成功但资料页空白”的中间态。

### 修复四：把 `selectedTab` 显式传入 UIKit Representable

Representable 增加 `selectedTab` 输入，并在 `updateUIViewController` 中同步到底层 controller：

```swift
private var tabBarHost: some View {
    TabBarControllerRepresentable(
        store: store,
        selectedTab: store.selectedTab
    )
}
```

```swift
func updateUIViewController(
    _ uiViewController: TabBarController,
    context: Context
) {
    uiViewController.syncSelectedTab(selectedTab)
}
```

UIKit controller 内部把 Tab 映射到 index，并只在必要时切换：

```swift
func syncSelectedTab(_ selectedTab: Tab) {
    let newIndex = selectedTab.index
    guard selectedIndex != newIndex else { return }
    switchChildViewController(toIndex: newIndex)
}
```

为什么这样修：SwiftUI Representable 的职责就是把 SwiftUI/TCA 状态投递给 UIKit 对象。让 UIKit controller 自己观察 store 会增加隐藏订阅和生命周期复杂度；显式参数 + `updateUIViewController` 更符合 SwiftUI 数据流。

### 为什么不采用其他修法

**不把后端登出失败直接展示为登出失败**：这会让用户被困在本地登录态中，尤其在服务端响应格式异常但本地 token 已不可信时，体验和安全语义都不合理。

**不在 View 层手动 dismiss 设置页**：手动 dismiss 只能处理当前 UI，不会清理 TCA state。下一次 body 计算时，只要 optional state 仍非 nil，modal 仍可能回来。

**不只依赖 session stream 异步刷新 user**：素材中的缺口正是 `setAccessToken` 路径没有更新 user。登录成功 action 已经携带 user，应该在父状态上同步闭环，再让 session stream 做后续一致性更新。

**不让 UIKit Tab 控制器私下读 Store**：UIKit 侧私下订阅会让状态来源分散，也容易出现订阅释放、重复更新和测试困难。Representable 的输入参数应是唯一桥接面。

---

## 可迁移原则

### 1. 登录/登出要按完整状态机链路审查

登出不是一个 API，登录也不是一个弹窗。至少要审查：触发、后端、清 session、清缓存、清子页、切 Tab、弹登录页、登录完成回填用户、恢复 pending 目标。任一节点漏掉，用户都会看到半登录态。

### 2. 客户端登出应优先保证本地状态一致

后端登出失败不应阻断本地清理。客户端应先把 UI、token、用户状态和受保护入口切到已登出态，再把远端清理视为 best-effort。这样可以避免“用户以为已登出，客户端仍显示已登录”的危险状态。

### 3. SwiftUI 状态驱动导航必须清理承载状态

`fullScreenCover`、sheet、navigation destination 这类导航都由状态驱动。关闭页面的根本动作是清掉对应 state，而不是只操作视图层。尤其是子页面内触发全局状态变化时，父状态必须同步收口。

### 4. Delegate action 是跨 Feature 同步写状态的好时机

子 Feature 完成登录、选择、支付、授权等动作后，delegate action 往往携带确定结果。父 Feature 应在这个边界同步写入关键状态，避免完全依赖异步通知链路。

### 5. SwiftUI + UIKit 混合时，Representable 必须显式同步输入状态

UIKit 对象不会天然观察 TCA Store。凡是 SwiftUI 状态会影响 UIKit 组件的属性，都应作为 Representable 的输入参数，并在 `updateUIViewController` 中幂等同步。

---

## 技术深问 Q&A

### Q1：为什么登出接口失败还要继续本地登出？

因为用户点击登出后，客户端身份状态必须立即失效。后端登出失败可能只是网络、超时或响应格式问题，不应让本地继续保留登录态。远端 token 可以依赖过期、重试或服务端策略处理。

### Q2：为什么 `fullScreenCover` 没有自动关闭？

SwiftUI 的状态驱动导航只认绑定状态。只要承载 modal 的 optional state 仍非 nil，`fullScreenCover` 就会继续展示。登出不会自动推断“设置页应该关闭”，必须在 reducer 中显式置 nil。

### Q3：登录成功后为什么不能等 session stream 回填用户？

可以等，但不应该只等。`loginCompleted(user)` 已经是确定结果，父状态机应立即写入用户，保证 UI 闭环。session stream 更适合作为后续同步和持久化一致性来源。

### Q4：`updateUIViewController` 为什么不能空实现？

Representable 是 SwiftUI 到 UIKit 的桥。SwiftUI 状态变化后，会通过 `updateUIViewController` 交给开发者同步到底层 UIKit 对象。空实现意味着 UIKit controller 保持旧状态，容易产生 `selectedTab` 与 `selectedIndex` 不一致。

### Q5：这类问题怎么测试？

可以用状态机测试覆盖关键 action 序列：`logoutTapped` 即使后端抛错也进入 `logoutSucceeded`；`logoutSucceeded` 后 `settings == nil`；`loginCompleted(user)` 后 `auth == nil` 且 `currentUser == user`；`selectedTab` 变化时 Representable 调用同步方法。

### Q6：为什么四个 bug 应该放在同一个闭环里理解？

因为它们都发生在同一条登录态状态机上。单独修某个点会改善一个现象，但用户流程仍可能被下一个断点卡住。登录态问题要按端到端闭环看，而不是按文件或按钮拆碎看。
