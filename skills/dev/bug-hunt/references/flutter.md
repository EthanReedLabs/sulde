# bug-hunt Flutter 参考(`mobile-flutter`)

> 配套 `../SKILL.md`。Flutter 特定 log / 工具 / 常见 pattern。

## §1 常见排查维度(Flutter)

| 维度 | 切入点 |
|---|---|
| Widget lifecycle | `initState` / `didChangeDependencies` / `dispose` / `mounted` 检查 |
| 状态管理 | Riverpod provider scope / Bloc 注册 / Provider 树 |
| 内存 | DevTools Memory tab / Stream subscription cancel / Controller dispose |
| 异步 | `async` / `await` 异常 / `Stream` 未关闭 / Future cancellation |
| 网络数据 | Dio interceptor / 错误处理 / Stream chain |
| UI 渲染 | `const` constructor / RepaintBoundary / ListView.builder |
| 平台桥接 | MethodChannel / EventChannel 失败 / 双端 native impl 不一致 |

## §2 拉证据命令

```bash
# Flutter logs
flutter logs > /tmp/flutter.log &

# DevTools(浏览器)
flutter pub global activate devtools
dart devtools --port 9100

# Android 端底层 log
adb logcat -d | grep -A 30 "flutter\|<package_name>" > /tmp/android-native.log

# iOS 端底层
xcrun simctl spawn booted log show --predicate 'process == "Runner"' --last 5m > /tmp/ios-native.log

# git log -S
git log -S "{symbol}" --since=30d --oneline -- lib/<relevant-module>/
```

## §3 常见 Bug pattern 速查

| 现象 | 常见根因 |
|---|---|
| setState after dispose | dispose 后 async work 还在跑 → `if (!mounted) return;` |
| Riverpod provider not found | `ProviderScope` 未包裹 / family 参数变化 |
| Bloc emit after close | `if (!isClosed) emit(...)` 检查缺 |
| Hot reload 后 state 残留 | `--release` / `--profile` 重启验真实状态 |
| Future double-fire | 没 cancel 之前的 Future / `Completer` 重用 |
| StreamSubscription leak | 没 `subscription.cancel()` in `dispose` |
| Platform channel timeout | Android / iOS 端 native impl 异常或未注册 |
| Overflowed by N pixels | `Expanded` / `Flexible` 缺 / 固定高 |

## §4 队友分配示例

1. **队友 1 — Widget tree + State**:Read Widget 树 + StatefulWidget lifecycle,看 mounted / dispose order
2. **队友 2 — Async + Stream**:Read async functions + Stream subscriptions,看 cancellation
3. **队友 3 — Platform channel**:若涉及 native,Read iOS + Android 双端 channel impl

> 占位说明:v0.2.1 初版基于 Flutter 3.x 常见 pattern。项目实际接入按采用的 state 库(Riverpod / Bloc / Provider)补充对应工具。
