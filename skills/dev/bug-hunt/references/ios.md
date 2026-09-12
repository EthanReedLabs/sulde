# bug-hunt iOS 参考(`mobile-ios`)

> 配套 `../SKILL.md`。iOS 特定 log / 工具 / 常见 pattern。

## §1 常见排查维度(iOS)

| 维度 | 切入点 |
|---|---|
| 生命周期 | `viewDidLoad` / `viewWillAppear` / scene lifecycle / app background |
| 状态管理 | TCA Reducer Action 分类 / `@Perception.Bindable` + `WithPerceptionTracking` 配对 |
| 内存 | Instruments Leaks / Memory Graph / `weak` capture 漏 |
| 线程并发 | `@MainActor` / Task vs DispatchQueue / Combine scheduler |
| 网络数据 | URLSession async / Combine error / SSE Publisher chain |
| UI 渲染 | SwiftUI body recompose / `Self._printChanges()` / List identity |
| 平台兼容 | iOS API availability / Xcode beta bug / Simulator vs 真机差异 |

## §2 拉证据命令

```bash
# 模拟器 log
xcrun simctl spawn booted log show \
    --predicate 'process == "<project>"' \
    --last 10m --style compact > /tmp/sim.log

# 真机 log(libimobiledevice)
idevicesyslog -u <UDID> > /tmp/device.log &

# crashreport
ls ~/Library/Logs/DiagnosticReports/<project>-*.{crash,ips} | tail -3

# Instruments record(轻量)
xcrun xctrace record --template "Time Profiler" --device <UDID> --time-limit 30s --output /tmp/profile.trace

# git log -S 反向搜索 symbol
git log -S "{symbol}" --since=30d --oneline -- Sources/<relevant-module>/
```

## §3 常见 Bug pattern 速查

| 现象 | 常见根因 |
|---|---|
| body 不刷新 | 漏 `WithPerceptionTracking { ... }` 包(iOS 16+ fallback) |
| List 错位 / 跳动 | id 不稳定(`UUID()` 每次 new)/ Identifiable hash 漂 |
| Sheet 闪退 | sheet state mutation 在 body 内(必 .task / .onAppear) |
| Effect 死循环 | Effect 触发同 Action / Scope keyPath 自指 |
| 网络后 UI 不更新 | Combine sink 漏 `.receive(on: DispatchQueue.main)` |
| Memory leak | `[weak self]` 漏 in closure / Combine sink 没 store(in: &cancellables) |
| EXC_BAD_ACCESS | 主线程外 UIKit / deallocated VC 上 push |
| Hang 卡死 | 主线程 IO / Core Data fetch / 大图同步 decode |

## §4 队友分配示例

3 队友常见分工:

1. **队友 1 — TCA 架构 + Action 分类**:Read Feature + Reducer + Dependency,看 Action 三分类 / Effect 错误处理 / Scope 嵌套
2. **队友 2 — View + Perception tracking**:Read SwiftUI Views,grep `@Perception.Bindable` 是否配对 `WithPerceptionTracking`,看 .task / .onAppear 时机
3. **队友 3 — 内存 + 主线程**:Read Combine pipelines,看 `[weak self]` / store(in:) / `.receive(on: main)` / `@MainActor` 漏
