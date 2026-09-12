# perf-diagnose Flutter 参考(`mobile-flutter`)

> 配套 `../SKILL.md`。Flutter 特定 profiler 命令 + 指标读法 + 平台模式。
>
> **占位说明**:本初版基于 v0.2.1,实际接入时按项目情况补充 — 项目落地的具体 .dart 路径 / package 版本 / CI benchmark 集成方式应在 PR 时实测确认。

## §1 工具速查表

| 维度 | 首选工具(GUI) | 自动化方案(命令行) |
|---|---|---|
| CPU / 调用栈 | DevTools CPU Profiler | `flutter run --profile --trace-startup` |
| 帧率量化(build/raster) | DevTools Performance | `flutter run --profile` + Performance overlay |
| 自定义时间线标记 | `Timeline.startSync` / `Timeline.timeSync` | 代码插桩 + DevTools Timeline |
| 帧流水线底层 | DevTools Frame Analysis | DevTools UI |
| 启动时间 | `flutter run --trace-startup` | `flutter run --profile --trace-startup --verbose` |
| 内存分配 | DevTools Memory | `dart devtools` + 进程 attach |
| 内存泄漏 | DevTools Memory(heap snapshot diff) | `dart devtools` |
| Widget 重建 | DevTools Performance "Track widget builds" | DevTools UI 切换 |
| 网络瀑布 | DevTools Network / Charles | `dart devtools` |
| 性能回归防护 | flutter_driver / integration_test benchmark | `flutter drive --profile --trace-startup` |
| 设备状态 | `flutter doctor -v` / `adb devices` / `xcrun devicectl` | 同 |

启动 DevTools:
```bash
flutter pub global activate devtools
dart devtools
# 浏览器打开 http://127.0.0.1:9100
# App 在 profile 模式跑,attach DevTools
```

---

## §2 按问题类型跑诊断套件

### §2.1 滚动卡顿 / jank — DevTools Performance

```bash
flutter run --profile -d <device-id>

# App 启动后,另开 terminal:
dart devtools
# 浏览器自动打开 → 选 Performance tab
```

DevTools Performance 视图关键 lane:
- **UI thread**:Dart 代码 + framework
- **Raster thread**(原 GPU thread):光栅化合成
- **Frame chart**:每帧 build / layout / paint / raster 各阶段耗时

**读法**:
- 任一阶段 > 16ms(60Hz)/ > 8ms(120Hz)= jank
- UI thread spike = Dart 代码慢(Widget rebuild / Layout)
- Raster thread spike = 渲染层过重(透明 / shader / 大图)

**Performance overlay**(运行时实时显示):
```dart
MaterialApp(
  showPerformanceOverlay: true, // 真机左上角显示 UI / Raster 两条曲线
  home: ...,
)
```

### §2.2 自定义时间线标记

```dart
import 'dart:developer';

Timeline.startSync('loadMoreTemplates');
try {
  await ref.read(templateRepoProvider).loadMore();
} finally {
  Timeline.finishSync();
}

// 或语法糖
await Timeline.timeSync('renderHeavyWidget', () async {
  // ...
});
```

DevTools Performance "Custom" 区段显示这些 sync。

### §2.5 启动时间

```bash
flutter run --profile --trace-startup -d <device-id>
# 启动完成后 trace 文件存到 build/start_up_info.json

cat build/start_up_info.json
# {
#   "engineEnterTimestampMicros": ...,
#   "timeToFirstFrameRasterizedMicros": ...,
#   "timeToFirstFrameMicros": ...,
#   "timeAfterFrameworkInitMicros": ...,
# }
```

关键阶段:
- `engineEnter` → engine 启动
- `timeToFrameworkInit` → Flutter framework 初始化
- `timeToFirstFrame` → 首帧构建完成
- `timeToFirstFrameRasterized` → 首帧上屏

冷启动总时长 = `timeToFirstFrameRasterized` < 2s 良好(中端机)。

### §2.7 内存

```bash
# DevTools Memory tab
dart devtools
# attach App → Memory tab
# - Allocation Profile:对象分配排行
# - Heap snapshot:两次快照 diff 找泄漏
# - Memory Chart:运行时曲线
```

**关键观察**:
- ImageCache 默认 100MB,大图列表易爆 → `PaintingBinding.instance.imageCache.maximumSizeBytes`
- `Stream` / `StreamController` 未 close → 持续累积
- `Provider` / `Riverpod` autoDispose 漏标 → State 不释放

### §2.13 性能回归防护

`integration_test` package + `flutter drive`:

```dart
// integration_test/scroll_benchmark_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:integration_test/integration_test_driver_extended.dart';

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized()
      as IntegrationTestWidgetsFlutterBinding;

  testWidgets('home feed scroll perf', (tester) async {
    app.main();
    await tester.pumpAndSettle();

    final listFinder = find.byType(ListView);
    await binding.traceAction(
      () async {
        await tester.fling(listFinder, const Offset(0, -500), 4000);
        await tester.pumpAndSettle();
      },
      reportKey: 'home_feed_scroll_timeline',
    );
  });
}
```

```bash
flutter drive \
  --driver=test_driver/perf_driver.dart \
  --target=integration_test/scroll_benchmark_test.dart \
  --profile \
  --no-dds
```

输出 `build/home_feed_scroll_timeline.timeline.json` + `.summary.json`,含 `average_frame_build_time_millis` / `worst_frame_build_time_millis` / `90th_percentile_frame_build_time_millis` / `99th_percentile_frame_build_time_millis`。

---

## §3 关键指标读法

| 指标 | 数据来源 | 阈值 |
|---|---|---|
| Build time per frame | DevTools / timeline.json | < 8ms 良好 / > 16ms jank |
| Layout time per frame | 同上 | 同上 |
| Paint time per frame | 同上 | 同上 |
| Raster time per frame | 同上 / Raster thread | 同上 |
| 99th percentile frame time | timeline.json summary | < 16ms 良好 |
| 首帧时间 | `start_up_info.json` `timeToFirstFrameRasterized` | < 2s |
| Widget rebuild 次数 | DevTools "Track widget builds" | 异常高 = key 不稳定 |
| ImageCache 大小 | Memory tab | 默认 100MB 上限 |

---

## §4 Flutter 特定性能反模式

- **缺 `const` 构造**:每次父 build 都新建子 widget → 整子树重建。修:所有 stateless leaf widget 加 `const`,且参数全 const-compatible。
- **`ListView` 不 builder**:`ListView(children: [...])` 一次性构建所有 cell。修:`ListView.builder` / `ListView.separated`,只构建可见区。
- **缺 `RepaintBoundary`**:某 widget 频繁重绘导致父子全部重栅格化。修:在重绘隔离边界包 `RepaintBoundary`(eg. 动画 widget 外层)。
- **`setState` 范围过大**:整个 StatefulWidget 重 build。修:状态局部化(`ValueListenableBuilder` / Riverpod 细粒度 provider)。
- **`Future.then` 在 build 中触发**:每次 build 重新订阅 Future,造成无限循环。修:`FutureBuilder` + state 缓存,或 `initState` 一次性订阅。
- **`MediaQuery.of(context)` 滥用**:任何 `MediaQuery` 变化导致整子树 rebuild。修:`MediaQueryData mq = MediaQuery.of(context)` 提至顶层 + 拆细参数。
- **图片不指定尺寸**:`Image.network(url)` 全分辨率解码到内存。修:`cacheWidth` / `cacheHeight` 限制解码尺寸 + `ResizeImage`。
- **`Stream` 未 cancel**:`StreamSubscription` 没在 `dispose()` 取消 → 泄漏 + 重复 build。修:`subscription.cancel()` in `dispose`。
- **`AnimationController` 未 dispose**:同上,加 `controller.dispose()`。

---

## §5 性能优化 checklist

- [ ] 所有 stateless leaf widget 加 `const`
- [ ] 长列表用 `ListView.builder` / `GridView.builder`
- [ ] 重绘频繁 widget 包 `RepaintBoundary`
- [ ] `setState` 范围最小化(局部 StatefulWidget / `ValueNotifier`)
- [ ] `MediaQuery` / `Theme.of` 在 build 顶部取一次
- [ ] `Image` 指定 `cacheWidth` / `cacheHeight`
- [ ] `Stream` / `AnimationController` / `TextEditingController` 在 dispose 释放
- [ ] DevTools "Track widget builds" 检查无高频无意义 rebuild
- [ ] Profile 模式实测,不在 Debug 模式下论结论(Debug 比 Release 慢 5-10x)

---

## §6 验证(repair verify)

```bash
# 1. 编译
flutter build apk --profile  # 或 ios --profile

# 2. install + launch
flutter install -d <device-id>
flutter run --profile -d <device-id> --trace-startup

# 3. 真机操作触达原性能场景

# 4. 跑同一 integration_test benchmark,对比 timeline summary 数值
flutter drive --driver=... --target=... --profile
diff <(jq . old.summary.json) <(jq . new.summary.json)
```

---

## §7 诊断 handoff 示例(摘录)

```markdown
## 诊断数据

| 指标 | 数值 | 工具 | 文件 |
|---|---|---|---|
| 99th percentile build time | 28ms | flutter drive timeline | timeline.summary.json |
| Raster thread max | 45ms | DevTools Performance | perf.screenshot |
| Widget rebuild 次数 | HomeFeedItem × 60/秒 | DevTools Track widget builds | screenshot |
| 首帧时间 | 2.8s | start_up_info.json | start_up_info.json |
| 内存峰值 | 380MB | DevTools Memory | mem.screenshot |

## Top-3 耗时来源

1. **`HomeFeedItem.build`** — 平均 18ms × 高频(占 60%)
   证据:Track widget builds 显示每次列表滚动整个 cell 重建,缺 const
2. **图片解码** — Raster thread 30ms spike
   证据:Image.network 未指定 cacheWidth,大图全分辨率解码
3. **`MediaQuery` 重渲染**
   证据:键盘弹起 → 整页 rebuild

## 排除项

- 网络层:接口 < 300ms 不在 jank 时段 → 排除
- Stream 泄漏:Memory 曲线平稳 → 排除
```
