---
doc_id: "ap-0165"
container: anti-patterns
platform: ios
summary: "0165 iOS 16 同一 NavigationStack 注册多个 navigationDestination 导…"
---

# 0165 iOS 16 同一 NavigationStack 注册多个 navigationDestination 导致 push 卡死

- **平台**:iOS
- **复发次数**:1

## ❌ 错误

在同一个 `NavigationStack` 宿主视图上注册两个或更多 `navigationDestination(isPresented:)`。在 iOS 16 推入后注册的目标页时，可能触发目标视图持续重算、CPU 与内存快速增长，最终由 watchdog 终止进程。

```swift
.navigationDestination(isPresented: $showFirst) { FirstView() }
.navigationDestination(isPresented: $showSecond) { SecondView() }
```

## 为什么错

- iOS 16 对同一栈中多个基于 `isPresented` 的 destination 支持不稳定，目标注册与视图求值可能互相触发。
- 新版系统可能已不复现，因此仅在新版模拟器验证会漏掉兼容性问题。
- 第二个入口若只存在于 Debug 条件编译中，Release 常规路径正常，会进一步掩盖根因。

## ✅ 正确

- 每个 `NavigationStack` 只保留一个 `navigationDestination`。
- 额外入口改用 `sheet` 或 `fullScreenCover`，并在模态内部按需建立独立的 `NavigationStack`。
- 呈现闭包依赖的 Store 或引用对象应由稳定生命周期持有，避免宿主重算时反复创建。
- 必须在最低支持系统的真机或等价运行环境验证导航路径。

## lint 状态

- ✅ 可 lint：按文件或同一视图节点统计 `navigationDestination`，达到两个时阻断或要求人工豁免。
- 人工 review：卡死并伴随 AttributeGraph 热点、watchdog 终止时，优先检查 destination 数量。
- 关联：SwiftUI 导航兼容性与最低系统版本验证。
