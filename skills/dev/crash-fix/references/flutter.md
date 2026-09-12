# crash-fix Flutter 参考(`mobile-flutter`)

> 配套 `../SKILL.md`。Flutter 特定日志命令 + 崩溃模式 + 验证。

## §1 拉日志命令

### runtime — flutter logs

```bash
# 实时 + 历史
flutter logs > /tmp/flutter.log &
LOG_PID=$!
# 期间触达原崩溃 / 手动操作
sleep 30
kill $LOG_PID
grep -i "exception\|error\|fatal\|stack" /tmp/flutter.log | tail -60

# 底层平台 log(Android 真机 / iOS 模拟器)
adb logcat -d | grep -A 30 "flutter\|FATAL" | tail -80              # Android 端
xcrun simctl spawn booted log show --predicate 'process == "Runner"' \
    --last 5m --style compact | tail -60                              # iOS 模拟器端
```

### build — flutter build

```bash
flutter analyze 2>&1 | grep -A 3 "error\|warning" | head -40

flutter build apk --debug 2>&1 | grep -A 3 "Error:\|error:" | head -40
flutter build ios --no-codesign --debug 2>&1 | grep -A 3 "error:" | head -40

# pubspec.yaml 解析
flutter pub get 2>&1 | tail -20
```

### frame drop / jank

```bash
flutter run --profile  # 然后用 DevTools 看 Performance tab
# 或:
adb shell dumpsys gfxinfo {package_name}.runner 2>&1 | grep -A 20 "Janky"
```

### 设备信息

```bash
flutter devices
flutter --version
grep "version:" pubspec.yaml | head -1
```

## §2 常见崩溃模式(Flutter)

| 异常 | 常见原因 | 检查点 |
|---|---|---|
| `Null check operator used on a null value` | `!` 强解包 null | `value!` / `value!.field` |
| `LateInitializationError` | `late` 变量未初始化就访问 | `late final` 修饰 + 初始化时机 |
| `_TypeError: type X is not subtype of Y` | 类型转换错 | `as` 转换 / generic 推断错 |
| `RangeError: index out of range` | 列表越界 | `list[index]` |
| `setState() called after dispose()` | dispose 后还 setState | `mounted` 检查缺失 |
| `Cannot get a TextDirection` | Widget 树缺 `Directionality` | 漏 `MaterialApp` / `Directionality` |
| `Overflowed by N pixels` | 布局溢出 | `Expanded` / `Flexible` 缺 / 固定高 |
| `ProviderException`(Riverpod)| provider 找不到 / 依赖循环 | provider 声明范围 / `ProviderScope` |
| `BlocStateNotFound`(Bloc)| Bloc 未注册 | `BlocProvider` 包裹 |
| `MissingPluginException` | platform channel 实现缺失 | platform-specific impl + register |

## §3 架构链路诊断(Flutter)

### Widget 树 / State 链路

- **setState 时机**:dispose 后 setState → `if (!mounted) return;` 检查
- **didChangeDependencies**:async work 启动后 widget 已 dispose
- **build 内 setState**:`build()` body 内调 `setState` → 无限重渲

### 状态管理(项目特定 — Riverpod / Bloc / Provider)

Riverpod:
- `Provider` 是否在 `ProviderScope` 内?
- `ref.watch` 时机(只能在 `build` / `Notifier` 内)
- `family` provider 参数变化导致 rebuild

Bloc:
- `BlocProvider` 是否包裹了使用该 Bloc 的子树?
- `emit` 在 `close` 后 → `if (!isClosed)` 检查
- Stream subscription 在 `close` 时清理

### Platform channel

```dart
// ❌ 容易崩
final result = await methodChannel.invokeMethod<String>('foo', args);

// ✅ 加 catch + 默认值
try {
  final result = await methodChannel.invokeMethod<String>('foo', args);
} on PlatformException catch (e) {
  // 处理 e.code / e.message
}
```

## §4 责任 Dev 路径前缀

Flutter 项目通常按 feature 分包,例如:

| 文件路径前缀 | 责任 Dev | 分支前缀 |
|---|---|---|
| `lib/feature_home/` | A | `dev/dev-a/` |
| `lib/feature_discover/` | A | `dev/dev-a/` |
| `lib/feature_create/` | B | `dev/dev-b/` |
| `lib/feature_inbox/` | C | `dev/dev-c/` |
| `lib/feature_profile/` | C | `dev/dev-c/` |
| `lib/core_ui/` | A | `dev/dev-a/` |
| `lib/core_network/` | C | `dev/dev-c/` |

项目本地 mapping 在 `<docs-hub>/page-owner-map.yaml`。

## §5 验证

```bash
# 1. analyze
flutter analyze | head -20

# 2. build + install
flutter build apk --debug
flutter install

# 3. 启动 + 触达原崩溃场景
flutter run --release  # 用 release / profile 模式,不是 hot reload
# (手动操作或 integration_test 脚本驱动)

# 4. 抓 30s log,无新 exception
flutter logs > /tmp/post-fix.log &
LOG_PID=$!
sleep 30
kill $LOG_PID
grep -i "exception\|error\|fatal" /tmp/post-fix.log | tail -20
```

**重要**:`flutter run`(hot reload 模式)state 会残留,可能掩盖 crash。验证必用 `--release` 或 `--profile` 模式。

## §6 Flutter 特定修复模式

- **Null 强解**:`value!` → `value ?? defaultValue` 或 `if (value != null) { ... }`
- **越界**:`list[index]` → `list.elementAtOrNull(index) ?? ...`(Dart 3.0+)
- **setState 后 dispose**:`setState(...)` → `if (mounted) setState(...)`
- **Future error**:`.then(...)` → `.then(...).catchError(...)`
- **Stream subscription**:`subscription.cancel()` in `dispose`
- **late 变量**:`late final foo = computeOnFirstUse()` 而非 `late final Foo foo;`
- **dispose order**:子 controller 先 dispose,父后(避免父调子)

## §7 跨平台 verify

Flutter 同 codebase 双端运行,**修复后必双端 verify**:

```bash
# Android
flutter build apk --debug && flutter install --device-id <android-id>
flutter logs --device-id <android-id> > /tmp/android-post.log &

# iOS
flutter build ios --debug --no-codesign
xcrun simctl install booted build/ios/iphonesimulator/Runner.app
xcrun simctl launch booted <bundle-id>
xcrun simctl spawn booted log show --predicate 'process == "Runner"' --last 5m > /tmp/ios-post.log
```

Handoff `§ verify` 必含 Android + iOS 两端 build + log 证据。

---

> **占位说明**:本 references/flutter.md 是 v0.2.1 初版,主要诊断工作流 / 命令 / 常见崩溃 pattern 已完整。Flutter 工具链(DevTools / `flutter run` 模式)+ state 库(Riverpod / Bloc / Provider)选择项目特定,实际接入时按采用方案补充对应工具命令 + 反模式。
