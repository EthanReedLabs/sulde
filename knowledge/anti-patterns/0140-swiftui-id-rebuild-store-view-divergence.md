---
doc_id: "ap-0140"
container: anti-patterns
platform: cross
summary: "0140 SwiftUI `.id(version)` 整树重建后 TCA store/view 发散"
---

# 0140 SwiftUI `.id(version)` 整树重建后 TCA store/view 发散

- **平台**:iOS(确认)/ Android(同类风险,见 Q4)
- **复发次数**:1

## ❌ 错误
用 `.id(version)` 强制重建视图树来刷新(典型:i18n 热切换),但 store 的导航/呈现状态不跟随复位:

```swift
mainStack
    .id(version)                          // 整树 teardown/rebuild → 视图落回首页
    .onReceive(pub) { _ in version += 1 } // 只 bump version,store 不动
// 结果:
//  ① store-driven cover(如 .fullScreenCover(item:) 绑定的呈现态)残留 → 回该 tab 又弹出
//  ② selectedTab 停在重建前的 tab → 点该 tab 时 state 无变化 → 同步选中态的桥不触发 → 切不过去
```

## 为什么错
- `.id()` 重建只复位 SwiftUI `@State`,**不动 TCA store**(SSOT 在 store,外部持有)→ store/view 发散。
- store-driven `.fullScreenCover(item:)` 的呈现态、`selectedTab` 等"重建前的位置"全部滞留。
- UIKit 桥(`UIViewControllerRepresentable` + 间接同步选中态)放大发散:无 state 变化 = 不刷新 = 不切。

## ✅ 正确
重建的**同一事件**里,把 store 协调复位到"重建后视图应处的干净状态":

```swift
.onReceive(pub) { _ in
    version += 1
    store.send(.contextDidReset)   // reducer: selectedTab = .home; presentation = nil
}
```

**原则**:凡用 `.id(动态值)` 强制重建**承载 store-driven 呈现/选中态**的子树,必在**同一触发点**把 store 复位到与重建落点一致。

## lint 状态
- ❌ 无法静态检查(需理解 `.id(version)` 重建 ↔ store-driven 呈现/`selectedTab` 的语义关系,grep 抓不住)→ 仅人工 review。建议进 `/code-review` checklist:"见 `.id(动态值)` 包裹含 store-driven cover / selectedTab 的子树 → 查是否同事件复位 store"。

## Q4 Android 同类风险
Android 配置变更走 `Activity.recreate()`,ViewModel(含选中态等)经 ViewModelStore **survive** → 同类"重建后 UI 落默认、VM 状态滞留"风险理论存在(机制不同,非照搬)。若出现"切语言/配置变更后底栏选中态或已开弹层与界面不一致",按 iOS 修法对照(同事件复位 VM 导航态)。
