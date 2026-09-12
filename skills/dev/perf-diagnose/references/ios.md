# perf-diagnose iOS 参考(`mobile-ios`)

> 配套 `../SKILL.md`。iOS 特定 profiler 命令 + 指标读法 + 平台模式。

## §1 工具速查表

| 维度 | 首选工具(GUI) | 自动化方案(命令行) |
|---|---|---|
| CPU / 调用栈 | Instruments Time Profiler | `xcrun xctrace record --template 'Time Profiler'` |
| SwiftUI 重渲(精确定位) | `Self._printChanges()` | 加一行代码看 Console |
| SwiftUI 重渲(量化) | Instruments SwiftUI Profiler | `xcrun xctrace --template 'SwiftUI'` |
| 自定义时间线标记 | `os_signpost` | 代码插桩 + Instruments Points of Interest |
| 帧率 / 动画 | Instruments Core Animation | `xcrun xctrace --template 'Core Animation'` |
| 启动时间 | Instruments App Launch | `xcrun xctrace --template 'App Launch'` / `devicectl --measure-launch-time` |
| 内存分配 | Instruments Allocations | `xcrun xctrace --template 'Allocations'` |
| 内存泄漏 / retain cycle | Xcode Memory Graph | `xcrun memgraph` + `xcrun leaks --memgraph` |
| 网络瀑布 | Charles / Proxyman | `idevicesyslog` 辅助 |
| Hang 检测 / 后台 / 启动指标 | MetricKit | App 内集成 `MXMetricManager` |
| 视图层级 | Xcode View Debugger | `xcrun devicectl captureScreenshot` 辅助 |
| 性能回归防护 | XCTest Performance | `xcodebuild test -only-testing:...` |

---

## §2 按问题类型跑诊断套件

设 `UDID="<your-device-udid>"` 贯穿示例。

### §2.1 滚动卡顿 / jank — CPU 火焰图

**Instruments Time Profiler(GUI)**:
```
1. Xcode → Product → Profile(⌘I) → 选 Time Profiler
2. Record,真机滚动 15s,Stop
3. 左侧 Call Tree:
   ✅ Hide System Libraries
   ✅ Invert Call Tree
4. 找主线程(Main Thread)上最宽的用户代码帧
5. 截图 Flame Chart + Heaviest Stack → .ai-workspace/diag/{date}-{slug}-flame.png
```

**自动化 `xctrace`(App 已运行时 attach)**:
```bash
UDID="<your-device-udid>"
OUTPUT=".ai-workspace/diag/$(date +%Y-%m-%d)-scroll-time-profiler.trace"
mkdir -p .ai-workspace/diag

xcrun xctrace record \
  --device "$UDID" \
  --template 'Time Profiler' \
  --attach-by-name <project-name> \
  --time-limit 15s \
  --output "$OUTPUT"

# 录制期间手动在真机滚动列表
open "$OUTPUT"
```

**读法**:
- 主线程宽帧 > 16ms = 掉帧根因
- `body` / `_makeBody` / `ForEach.update` 频繁 = SwiftUI 过度重渲
- `AVPlayer.init` / `AVQueuePlayer` 在主线程 = 媒体初始化阻塞
- Wall Clock > CPU Time = 等锁或 IO

### §2.2 SwiftUI 重渲(关键 — iOS 特有)

#### `Self._printChanges()` 一行代码定位

```swift
var body: some View {
    let _ = Self._printChanges()  // Console 打印触发重渲的具体属性
    // 原 body 内容不动
}
```

Console 输出读法:
```
HomeFeedView: _store changed.            ← store 整体变化触发重渲
TemplateCardView: @self changed.        ← 视图自身重建(Equatable 未实现)
masonryGrid: _templates changed.       ← 具体是 templates 数组变了
```

每帧都打印 = 该 View 在每帧重算 body → 性能瓶颈。**完成后必须删除此行**(不能进 release build)。

#### SwiftUI Instruments

```bash
UDID="<your-device-udid>"
OUTPUT=".ai-workspace/diag/$(date +%Y-%m-%d)-swiftui-profiler.trace"

xcrun xctrace record \
  --device "$UDID" \
  --template 'SwiftUI' \
  --attach-by-name <project-name> \
  --time-limit 15s \
  --output "$OUTPUT"

open "$OUTPUT"
```

读法:
- View Body Invocations 列:找调用次数异常多的 View(`ForEach` 每帧重算)
- Duration > 5ms 的单次重算 = 重点
- `EquatableView` 命中率低 = diff 代价高

### §2.3 帧率(Core Animation)

```bash
UDID="<your-device-udid>"
OUTPUT=".ai-workspace/diag/$(date +%Y-%m-%d)-core-animation.trace"

xcrun xctrace record \
  --device "$UDID" \
  --template 'Core Animation' \
  --attach-by-name <project-name> \
  --time-limit 15s \
  --output "$OUTPUT"

open "$OUTPUT"
```

读法:FPS 曲线低于 60(ProMotion 设备 120)的帧段,对照 Time Profiler 时间轴找对应 CPU 活动。

### §2.5 启动时间

```bash
UDID="<your-device-udid>"

# devicectl(Xcode 15+,精确)
xcrun devicectl device process launch \
  --device "$UDID" \
  --measure-launch-time \
  <your-app-bundle-id>

# idevicesyslog 捕获 MetricKit / os_signpost(需 libimobiledevice)
idevicesyslog -u "$UDID" | grep -E "launch|MetricKit|applicationDidFinish"
```

**Instruments App Launch**:
```bash
UDID="<your-device-udid>"
OUTPUT=".ai-workspace/diag/$(date +%Y-%m-%d)-app-launch.trace"

xcrun xctrace record \
  --device "$UDID" \
  --template 'App Launch' \
  --launch -- <your-app-bundle-id> \
  --output "$OUTPUT"

open "$OUTPUT"
```

主线程上 pre-main(dyld 加载)/ post-main(`+initialize` / `application(_:didFinishLaunchingWithOptions:)`)各占多少。

### §2.7 内存(Allocations)

```bash
UDID="<your-device-udid>"

xcrun xctrace record \
  --device "$UDID" \
  --template 'Allocations' \
  --attach-by-name <project-name> \
  --time-limit 30s \
  --output ".ai-workspace/diag/$(date +%Y-%m-%d)-allocations.trace"
```

**Instruments Allocations(GUI)**:
1. Profile → Allocations
2. Record → 触发疑似增长操作(多次进出 / 翻页)
3. All Heap Allocations 增长曲线
4. Mark Generation:操作前后各标一次,看 delta 最大对象类型

**Instruments Leaks**:
1. Profile → Leaks
2. Record → 操作 → Stop
3. Leaks 红色 X = 确认泄漏
4. 点对象 → Stack Trace → 找 retain cycle

### §2.9 内存泄漏 — Memory Graph(比 Leaks 更直观)

**Xcode GUI**:
```
1. 真机运行 → 触发疑似增长
2. Debug 区域底部工具栏 → "Debug Memory Graph"
3. 左侧列存活对象,点对象看引用链:
   - 紫色 ⚠️ = rootless 引用(系统判定泄漏)
   - 箭头图 = 可视化 retain cycle
4. 搜索框输入项目类名筛自己代码
5. File → Export Memory Graph(.memgraph)
6. 截图 → .ai-workspace/diag/{date}-{slug}-memgraph.png
```

**命令行(无需 GUI)**:
```bash
UDID="<your-device-udid>"
PID=$(xcrun devicectl device info processes --device "$UDID" 2>/dev/null \
  | grep -i <project-name> | head -1 | awk '{print $1}')

xcrun memgraph -p "$PID" \
  ".ai-workspace/diag/$(date +%Y-%m-%d)-app.memgraph"

# 命令行分析 retain cycle
xcrun leaks --memgraph ".ai-workspace/diag/$(date +%Y-%m-%d)-app.memgraph" \
  | grep -E "Leak|cycle|<project-name>"

# 堆对象排行
xcrun heap --memgraph ".ai-workspace/diag/$(date +%Y-%m-%d)-app.memgraph" \
  | head -30
```

### §2.10 主线程阻塞 / Hang(MetricKit)

App 内集成:
```swift
import MetricKit

class MetricsHandler: NSObject, MXMetricManagerSubscriber {
    func didReceive(_ payloads: [MXMetricPayload]) {
        // payload.applicationLaunchMetrics.histogrammedTimeToFirstDraw
        // payload.applicationResponsivenessMetrics.histogrammedApplicationHangTime
    }
    func didReceive(_ payloads: [MXDiagnosticPayload]) {
        // payload.hangDiagnostics(每次 hang 时间 + 调用栈)
    }
}
```

iOS 14+ MetricKit hang 检测在 Console.app 也有体现:
```bash
# Mac Console.app 连真机,过滤 "Hang detected"
idevicesyslog -u "$UDID" | grep -i "hang"
```

### §2.11 网络瀑布(Charles)

**真机配置(一次性)**:
```
1. Mac:Charles → Proxy Settings → port 8888
2. 真机:Wi-Fi → HTTP 代理 → Mac IP:8888
3. Mac:Help → SSL Proxying → Install Charles Root Certificate on iOS device
4. 真机:Settings → General → VPN & Device Management → 信任 Charles 证书
5. Charles:Proxy → SSL Proxying Settings → Host: *
```

**录制**:
```
1. Charles ⌘K 清空 → Start Recording
2. 真机重现慢操作
3. Stop
4. View → Charts → Timeline → 串行/并行瀑布图
5. 关键请求 → Timing tab → DNS / Connect / SSL / Send / Wait / Receive
6. 截图 → .ai-workspace/diag/{date}-{slug}-network.png
```

**辅助(idevicesyslog 抓 URLSession 日志)**:
```bash
UDID="<your-device-udid>"

idevicesyslog -u "$UDID" 2>/dev/null \
  | grep -E "HTTP|URLSession|NSURLSession|error|timeout|<project-name>" \
  | tee ".ai-workspace/diag/$(date +%Y-%m-%d)-network-log.txt"
```

### §2.2 自定义时间线标记(`os_signpost`)

```swift
import os.signpost

private let perfLog = OSLog(subsystem: "ai.<project>", category: .pointsOfInterest)

// 区间型
os_signpost(.begin, log: perfLog, name: "loadMoreTemplates")
store.send(.view(.loadMoreTemplates))
os_signpost(.end, log: perfLog, name: "loadMoreTemplates")

// 事件型
os_signpost(.event, log: perfLog, name: "templateAppear", "%{public}s", template.id)
```

Instruments Time Profiler 勾选左侧 "Points of Interest" lane,signpost 区间与 CPU spike 时间轴对齐。

### §2.12 视图层级 / 过度绘制

**Xcode View Debugger(GUI)**:
1. 真机运行 → 导航到目标页面
2. Xcode → Debug → View Hierarchy(或工具栏 📱 图标)
3. 3D 图层:
   - 层叠 > 5 层 = 过度绘制
   - 透明 View 叠加 = GPU 负担
4. 找 constraint ambiguity(黄色警告)

**截图辅助**:
```bash
UDID="<your-device-udid>"

xcrun devicectl device captureScreenshot \
  --device "$UDID" \
  ".ai-workspace/diag/$(date +%Y-%m-%d)-screenshot.png"
```

### §2.13 性能回归防护(XCTest Performance)

```swift
import XCTest

final class HomeFeedScrollPerformanceTests: XCTestCase {
    let app = XCUIApplication()

    override func setUp() {
        continueAfterFailure = false
        app.launch()
    }

    func testHomeFeedScrollPerformance() throws {
        app.tabBars.buttons["HomeFeed"].tap()
        let list = app.scrollViews.firstMatch
        XCTAssertTrue(list.waitForExistence(timeout: 5))

        measure(metrics: [XCTOSSignpostMetric.scrollDecelerationMetric]) {
            list.swipeUp(velocity: .fast)
            list.swipeDown(velocity: .fast)
        }
        // 默认 5 次取均值,超基线 10% 标黄,20% 报错
    }

    func testLoadMoreTiming() throws {
        app.tabBars.buttons["HomeFeed"].tap()
        let list = app.scrollViews.firstMatch
        XCTAssertTrue(list.waitForExistence(timeout: 5))

        measure(metrics: [XCTClockMetric()]) {
            list.swipeUp(velocity: .fast)
            list.swipeUp(velocity: .fast)
            list.swipeUp(velocity: .fast)
        }
    }
}
```

```bash
xcodebuild test \
  -project <project-name>.xcodeproj \
  -scheme <project-name> \
  -destination 'platform=iOS,id=<your-device-udid>' \
  -only-testing:<project-name>UITests/HomeFeedScrollPerformanceTests \
  ENABLE_DEBUG_DYLIB=NO \
  2>&1 | grep -E "measured|average|baseline|failed|error"
```

Xcode 自动对比历史基线,退化在 CI 报错。

---

## §3 关键指标读法

| 指标 | 数据来源 | 阈值 |
|---|---|---|
| FPS(滚动时) | Core Animation Instrument | < 55fps(60Hz)/ < 110(120Hz)= jank |
| 主线程最大 spike | Time Profiler Heaviest Stack | > 16ms = 单帧掉帧 |
| View Body 调用次数 | SwiftUI Instrument | 同一 View 每帧重算 = 重渲 bug |
| 启动时间 | `devicectl --measure-launch-time` | 冷启动 < 1.5s 良好 |
| Allocations 增长曲线 | Allocations Instrument | 操作前后 delta > 50MB 警惕 |
| Hang time | MetricKit / Console | > 250ms 即用户感知 |
| URLSession Call Time | Charles Timing | WiFi < 800ms 良好 |

---

## §4 iOS 特定性能反模式

- **SwiftUI body 过度重算**:`@ObservedObject` 整个 store 触发整页重渲。修:细化 `@Published` 粒度 / `EquatableView` / `@StateObject` 子拆 / `let _ = Self._printChanges()` 定位。
- **图片解码在主线程**:`UIImage(named:)` 大图直接载入主线程。修:Nuke / Kingfisher / SDWebImage 异步,或 `prepareForDisplay()`(iOS 15+)。
- **Combine 调度器误用**:`.receive(on: DispatchQueue.global())` 漏掉 `.receive(on: DispatchQueue.main)` 回 UI。修:严格区分 IO/CPU 调度器与 UI 调度器。
- **`fullScreenCover` / `sheet` 链式重建**:多层 modifier 嵌套触发整链重算。修:`@State` 提至共同祖先 / 用 `.background` 而非 `.overlay`。
- **TCA `WithPerceptionTracking` 漏配对**:iOS 16+ `@Perception.Bindable` 必配 `WithPerceptionTracking { }` 否则不重渲。详 反模式集合(项目特定)。
- **`AVPlayer` 同步初始化**:主线程 `AVPlayer(url:)` + `play()` 阻塞 100~300ms。修:后台 thread 预热 + `playerItem.preferredForwardBufferDuration`。
- **`Date()` / `DateFormatter` 在 cell 每次重算**:格式化器昂贵。修:`static let` 缓存 + `ISO8601DateFormatter`(线程安全)。
- **`String(format:)` / 正则在主线程频繁**:profiler 显示在 cellForRowAt 路径上。修:预格式化 + cache。

---

## §5 SwiftUI 性能优化 checklist

- [ ] 用 `let _ = Self._printChanges()` 定位高频重算 View
- [ ] `ForEach` 的 `id:` 用稳定唯一标识(不是 `UUID()` 每次新建)
- [ ] 列表用 `LazyVStack` / `LazyHStack` 而非 `VStack`
- [ ] 不变内容 + Equatable struct + `.equatable()` modifier
- [ ] `@State` 局部,`@StateObject` 视图级,`@ObservedObject` 上游注入
- [ ] 复杂 body 拆 subview 减少 diff 单元
- [ ] 图片用 `AsyncImage`(iOS 15+)或 Nuke,避免主线程解码
- [ ] 动画用 `withAnimation` 显式控制,不要散布隐式触发

---

## §6 真机性能验证(repair verify)

```bash
UDID="<your-device-udid>"

# 1. 编译
xcodebuild -project <project-name>.xcodeproj \
  -scheme <project-name> \
  -destination "platform=iOS,id=$UDID" \
  build

# 2. install + launch
xcrun devicectl device process launch \
  --device "$UDID" \
  --measure-launch-time \
  <your-app-bundle-id>

# 3. 真机操作触达原性能场景(手动或 XCUITest 驱动)

# 4. 再跑一次同一 profiler,对比基线
xcrun xctrace record --device "$UDID" --template 'Time Profiler' \
  --attach-by-name <project-name> --time-limit 15s \
  --output ".ai-workspace/diag/$(date +%Y-%m-%d)-after-fix.trace"
```

fix 验证三联:
1. 同操作场景 → 复测同一指标(P99 / Janky% / Hang count / 内存峰值)
2. 对比基线数值(诊断 handoff 中已记录)
3. 改善幅度符合预期 → 通过

---

## §7 诊断 handoff 示例(摘录字段)

```markdown
## 诊断数据

| 指标 | 数值 | 工具 | 文件 |
|---|---|---|---|
| FPS(滚动) | 38fps(120Hz 设备应 110+) | Core Animation | core-anim.trace |
| 主线程最大 spike | 95ms (FeedItemView.body) | Time Profiler | flame.png |
| body 重算次数 | FeedItemView 每帧 3 次 | SwiftUI Profiler | swiftui.trace |
| Hang count | 5 次 / 30s | MetricKit | hang.log |
| 内存峰值 | 480MB | Allocations | alloc.trace |
| 接口 1 | 1.2s | Charles | network.png |

## Top-3 耗时来源

1. **`FeedItemView.body`** — 每帧 35ms × 3 次(占 60%)
   证据:flame.png Heaviest Stack + Self._printChanges 显示 `@self changed`
2. **`AVPlayer.init`** — 主线程 120ms
   证据:Time Profiler 主线程宽块 + Wall Clock = CPU Time
3. **GET /api/v1/feed** — 1.2s
   证据:Charles Timing tab Wait 段 800ms

## 排除项

- 图片解码:已用 Nuke 异步,profiler 不在主线程 → 排除
- Combine 调度器:已 receive(on: main) → 验证无误,排除
```
