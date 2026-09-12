# crash-fix iOS 参考(`mobile-ios`)

> 配套 `../SKILL.md`。iOS 特定日志命令 + 崩溃模式 + 验证。

## §1 拉日志命令

### simulator(模拟器崩溃)

```bash
# 检查启动的模拟器,没有则启动
BOOTED=$(xcrun simctl list devices booted -j 2>/dev/null | python3 -c "
import sys, json
devs = [d for r in json.load(sys.stdin)['devices'].values() for d in r if d['state']=='Booted']
print(devs[0]['udid'] if devs else '')
" 2>/dev/null)

if [ -z "$BOOTED" ]; then
    echo "启动 iPhone 17 Pro..."
    xcrun simctl boot "iPhone 17 Pro" 2>/dev/null
    sleep 3
    open -a Simulator
fi

# 方式 1:从 DiagnosticReports 拉(最可靠)
CRASH_LOG=$(ls -t ~/Library/Logs/DiagnosticReports/<project>-*.crash \
                  ~/Library/Logs/DiagnosticReports/<project>-*.ips 2>/dev/null | head -1)
if [ -n "$CRASH_LOG" ]; then
    echo "=== 找到崩溃日志: $CRASH_LOG ==="
    cat "$CRASH_LOG" | head -120
fi

# 方式 2:从模拟器实时日志(App 正在运行或刚崩)
xcrun simctl spawn booted log show \
    --predicate 'process == "<project>"' \
    --last 5m --style compact 2>/dev/null | \
    grep -i "fatal\|crash\|exception\|error\|assert\|EXC_\|BUG IN CLIENT\|signal" | tail -40

# 方式 3:完整 App 日志(若以上都无)
xcrun simctl spawn booted log show \
    --predicate 'process == "<project>"' \
    --last 10m --style compact 2>/dev/null | tail -60
```

### device(真机崩溃)

```bash
# 拉真机 CrashReporter
ls -t ~/Library/Logs/CrashReporter/MobileDevice/*/<project>-*.ips 2>/dev/null \
    | head -1 | xargs cat | head -100

# 或 devicectl(Xcode 15+)
xcrun devicectl device info logs \
    --device "$(xcrun devicectl list devices 2>/dev/null | grep -v Simulator | tail -1 | awk '{print $NF}')" 2>/dev/null \
    | grep -i "<project>\|crash\|exception" | tail -50

# idevicesyslog 实时(libimobiledevice)
idevicesyslog -u <UDID> | grep -i "fatal\|crash\|exception\|EXC_\|signal" | tail -60
```

### build(编译错误)

```bash
# 模拟器 build
xcodebuild -project <project>.xcodeproj -scheme <project> \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -skipMacroValidation build 2>&1 | grep -A 3 "error:\|fatal error:" | head -60

# 真机 build(必加 ENABLE_DEBUG_DYLIB=NO)
xcodebuild -project <project>.xcodeproj -scheme <project> \
  -destination 'platform=iOS,id=<UDID>' \
  -allowProvisioningUpdates -skipMacroValidation \
  ENABLE_DEBUG_DYLIB=NO build 2>&1 | grep -A 3 "error:" | head -60

# SPM 解析错误
swift package resolve 2>&1 | tail -20
```

### 设备 / 模拟器信息

```bash
xcrun simctl list devices booted | head -5
xcodebuild -version
grep -A 1 "MARKETING_VERSION\|CFBundleShortVersionString" <project>.xcodeproj/project.pbxproj | head -4
```

## §2 常见崩溃模式(iOS)

| 异常 | 常见原因 | 检查点 |
|---|---|---|
| `EXC_BAD_ACCESS` | 野指针 / 已释放对象 | UIKit 主线程检查、`@MainActor` 漏 |
| `Fatal error: unexpectedly found nil` | 强解包 Optional | `state.xxx!` / `as!` 类型转换 |
| `Thread 1: signal SIGABRT` | `assert` / `precondition` / `fatalError` 失败 | 代码中 `fatalError(...)` |
| `Type mismatch in Scope` | TCA Scope keyPath 错 | `\.child` 路径 vs Action case |
| `Missing dependency` | `@Dependency` 未注册 | `DependencyValues` extension |
| `Array index out of range` | 越界访问 | `array[index]` 应改 `safe:` subscript |
| `Cannot find type` | SPM module 未 import / target 未配 | `Package.swift` dependencies |
| `BUG IN CLIENT OF LIBSQLITE3` | Core Data / SQLite 多线程 | NSManagedObjectContext queue 违规 |
| Hang detected | 主线程 > 2s | 网络 / 大图 / 同步 IO 在 main |
| `Encountered an unrecoverable error` | SwiftUI body 更新 cycle 内 | `@State` mutate in body |

## §3 架构链路诊断(iOS TCA)

崩溃在 Feature / Reducer 中:

- **Action 三分类**:View Action 可 `.run`,Result Action 只 `.none` 或 `.send(.delegate)`,Delegate Action 父 Reducer 处理后 `.none`
- **@Dependency 注入**:`liveValue` / `testValue` / `previewValue` 都注册了吗?
- **Effect async / try**:每个 try 都有 catch?`try?` 应限于不影响业务的场景
- **State Optional 强解**:`state.xxx!` → `guard let xxx = state.xxx else { return .none }`
- **Scope 嵌套**:keyPath / casePath 正确?`childAction` case 名匹配?

崩溃在 View / SwiftUI 中:
- **Perception tracking 配对**:`@Perception.Bindable` + `WithPerceptionTracking { ... }` 必同时(iOS 16+ fallback)
- **@State mutate in body**:body 内调用 `.task { self.state = ... }` ⚠️
- **EnvironmentObject 缺失**:某 View 用 `@EnvironmentObject` 但父 chain 未 inject
- **NavigationStack path mutation**:`path.append` 在 body 内
- **List / ForEach Identifiable**:id 重复或动态变化

崩溃在 UIKit 中:
- **主线程**:UIKit API 必 main thread,跑 background 时 `DispatchQueue.main.async`
- **deinit 时移除 KVO / NotificationCenter observer**:观察者泄漏 → crash on `removeObserver:`
- **window scene 在 SceneDelegate 未初始化时访问**:app 启动早期 access `view.window` 为 nil
- **AutoLayout 矛盾约束**:debug 时 console 有 warning,运行时可能 fail
- **deallocated UIViewController 上的 navigation push**:nav stack pop 后再 push

## §4 责任 Dev 路径前缀(示例,项目可自定义)

> ⚠️ **占位示例 — 替换为你的项目**
> 下方 table 是某移动创作 app 的 Dev / 模块 mapping,**仅作格式示例**。你的项目应:
> 1. **优先方式**:在 `<docs-hub>/page-owner-map.yaml` 显式定义本项目的 module → Dev mapping
> 2. **备选方式**:用 `.sulde-config.yaml: team[]` alias 配合实际 module 名替换下表的 `A/B/C` + `Sources/FeatureHome/...`

| 文件路径前缀 | 责任 Dev | 分支前缀 |
|---|---|---|
| `Sources/FeatureHome/` | A | `dev/dev-b/` |
| `Sources/FeatureDiscover/` | A | `dev/dev-b/` |
| `Sources/FeatureDetail/` | A | `dev/dev-b/` |
| `Sources/<FeatureSampleAgent>/` | B | `dev/dev-d/` |
| `Sources/<FeatureSampleRealtime>/` | B | `dev/dev-d/` |
| `Sources/CoreUI/` | B | `dev/dev-d/` |
| `Sources/FeatureInbox/` | C | `dev/dev-f/` |
| `Sources/FeatureProfile/` | C | `dev/dev-f/` |
| `Sources/FeatureAuth/` | C | `dev/dev-f/` |
| `Sources/InfraNetwork/` | C | `dev/dev-f/` |
| `Sources/InfraStorage/` | C | `dev/dev-f/` |
| `Sources/<project>App/` | A | `dev/dev-b/` |
| `Sources/Spec/` | A | `dev/dev-b/` |

项目本地 mapping 应在 `<docs-hub>/page-owner-map.yaml` 或 `.sulde-config.yaml`。

## §5 验证(repair verify)

```bash
# 1. 模拟器编译
xcodebuild -project <project>.xcodeproj -scheme <project> \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -skipMacroValidation build

# 2. 真机编译 + install + launch
xcodebuild -project <project>.xcodeproj -scheme <project> \
  -destination 'platform=iOS,id=<UDID>' \
  -allowProvisioningUpdates -skipMacroValidation \
  ENABLE_DEBUG_DYLIB=NO clean build

APP_PATH=$(find ~/Library/Developer/Xcode/DerivedData/<project>-*/Build/Products/Debug-iphoneos \
    -maxdepth 1 -name "<project>.app" -exec stat -f "%m %N" {} \; | sort -rn | head -1 | cut -d' ' -f2-)
ios-deploy --id <UDID> --bundle "$APP_PATH" --justlaunch

# 3. 触达原崩溃场景(手动操作或脚本)

# 4. 抓 30s log,无新 crash
idevicesyslog -u <UDID> > /tmp/post-fix.log &
LOG_PID=$!
sleep 30
kill $LOG_PID
grep -i "fatal\|crash\|exception\|EXC_" /tmp/post-fix.log | tail -20
```

验证全过 → handoff `§ verify` 段含上述 4 步证据。

## §6 iOS 特定修复模式

- **强解包**:`state.xxx!` → `guard let xxx = state.xxx else { return .none }`
- **Cast**:`obj as! Foo` → `guard let obj = obj as? Foo else { return }`
- **越界**:`array[index]` → `array[safe: index] ?? ...`(项目内有 safe subscript extension)或先 `guard index < array.count`
- **主线程**:UI 更新 `await MainActor.run { ... }` 或方法标 `@MainActor`
- **Perception tracking**:View 漏 `WithPerceptionTracking` → 加 wrapper
- **Optional chaining 兜底**:`obj?.field?.nestedField ?? defaultValue`
- **TCA Scope keyPath**:确认 `\.child` 与 reducer 内 case 名匹配
- **`@Dependency` 未注册**:实现 `DependencyValues` extension + `liveValue`

## §7 Hang / 长卡修复(主线程 > 2s)

iOS 用 MetricKit / Instruments Hang Detector 抓:

```bash
# Instruments 抓 Hang
xcrun xctrace record --template "Hangs" --device <UDID> --output /tmp/hang.trace --time-limit 60s

# 真机 hang report
ls ~/Library/Logs/DiagnosticReports/<project>-*.hang
```

修复方向:
- 网络同步调用 → URLSession async / await
- Core Data 主线程 fetch → `perform { ... }` background context
- 大图像加载 → Kingfisher / SDWebImage(自动 background)
- 同步文件 IO → `FileManager` 移 background queue
- `Thread.sleep` 在主线程 → 严禁,改 Task / Timer

## §8 TCA 特定模式

```swift
// ❌ 错:可能崩
@Reducer
struct Foo {
  var body: some ReducerOf<Self> {
    Reduce { state, action in
      switch action {
      case .didTapButton:
        return .run { send in
          let value = try await client.fetch()  // ❌ try 没 catch
          await send(.dataLoaded(value))
        }
      // ❌ 漏 case → switch 不全 → 编译报错
      }
    }
  }
}

// ✅ 对:
return .run { send in
  do {
    let value = try await client.fetch()
    await send(.dataLoaded(value))
  } catch {
    await send(.dataFailed(error))
  }
}
```
