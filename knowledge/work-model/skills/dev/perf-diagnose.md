---
doc_id: "work-model/skills/dev/perf-diagnose"
container: work-model
platform: cross
summary: "Android/iOS Dev 在提出性能 fix 前以数值、trace 与截图建立可复测诊断证据。"
---

# 性能诊断（Android / iOS）

核心门控：**Measure First**。没有实测数值与截图/trace，不输出 fix 结论。

## 1. 确认边界

一次只选择一个主要症状：滚动卡顿、启动/进场慢、内存增长、网络慢、动画掉帧或主线程阻塞。记录冷/热态、设备与系统、网络、数据规模、复现步骤、用户感知和正常 baseline。诊断前固定变量，至少重复三次；启动类建议五次并报告中位数与离散度。

## 2. 选择诊断套件

### 滚动、动画与重渲染

Android:
- `dumpsys gfxinfo <包名> framestats` 量化总帧、janky frames 与分位数。
- Perfetto 或 Android Studio CPU Profiler 定位主线程、RenderThread、锁与 IO；保存 trace 和关键截图。
- GPU 过度绘制、SurfaceFlinger frame latency 用作渲染深挖。
- Compose 结合 recomposition/布局检查，确认列表 item 是否在组合期做同步 IO 或对象创建。

iOS:
- Instruments Time Profiler/Core Animation 获取主线程火焰图、帧率和 hitch。
- SwiftUI 用 `Self._printChanges()` 定位无效重渲染；UIKit 检查 layout/display 热点。
- `os_signpost` 标记用户动作到首帧、动画阶段和异步任务边界。
- View Debugger/截图检查层级与过度绘制。

### 启动与进场

Android:
- `am start-activity -W` 或 logcat `Displayed`；冷启动前强停，区分 ThisTime/TotalTime/WaitTime。
- 用 Perfetto/Startup Profiler 拆分进程创建、Application、首帧和页面数据阶段。

iOS:
- 用 Instruments App Launch、`devicectl` 与 signpost 测量进程启动、首帧和页面可交互时间。
- 区分 pre-main、App/Scene 生命周期、首屏 body/layout 与首个 effect。

### 内存与 OOM

Android:
- `dumpsys meminfo` 建立前后快照；Profiler/heapprofd 区分托管堆、native、graphics 与泄漏链。

iOS:
- Allocations/Leaks/Memory Graph 或 memgraph 建立前后快照；区分持有环、图片峰值、缓存和 native 分配。

两端都必须执行“进入→退出→重复”循环，确认是峰值、缓存平台还是单调增长。

### 网络与主线程 IO

Android:
- 网络瀑布图结合 OkHttp/系统日志；StrictMode 暴露磁盘和网络主线程访问。

iOS:
- 网络瀑布图结合 URLSession metrics/log；Main Thread Checker 与 Time Profiler 验证主线程阻塞。

两端共同拆分 DNS、连接、TLS、TTFB、下载、解析和首帧消费，避免把服务端等待误判为 UI 问题。

## 3. 诊断结论门控

结论必须同时包含：

- baseline 与问题场景的同口径数值；
- 至少一份 trace/火焰图/内存图/瀑布图或截图；
- top-3 耗时或增长来源，逐项标记“实测”或“待验证”；
- 已排除项及证据；
- fix 方向对应哪一个已测瓶颈；
- 修复后的同设备、同数据、同操作复测计划。

## 4. handoff 模板

```markdown
# 性能诊断报告：{症状}
- 平台 / 设备 / 系统：
- 冷热态、网络、数据规模：
- 复现步骤：
- baseline：
- 实测数值（至少三次）：
- top-3 来源（证据链接）：
- 排除项：
- 截图 / trace 清单：
- 有数据支撑的 fix 方向：
- 验收阈值与复测方法：
```

写入本端 handoff 后通知协调端；不直接修改跨端任务或共享真相。

## 禁止

- 看到“慢”就改缓存、并发或动画。
- 只有主观描述，没有毫秒、帧率、内存或网络阶段数值。
- 只给优化建议，不留 trace/截图。
- 更换设备、数据或冷热态后声称修复有效。
- 为测量永久保留调试插桩；临时插桩必须可定位并在交付前清理。
