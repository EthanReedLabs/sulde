---
doc_id: "work-model/perf-diagnosis"
container: work-model
platform: none
summary: "源自某次秒级延迟多轮盲修复复盘。"
---

# 性能诊断 SOP(三端共享)

> 源自某次秒级延迟多轮盲修复复盘。
> v2 升级:全维度工具矩阵 + 双模式（手动 GUI / 终端自动化）。
> 三端共享铁律：诊断门控 + 多维工具套件。

---

## 核心原则

**Measure First，禁止 Guess First。**

任何涉及"慢/卡/延迟/优化/提速/卡顿/抖动/掉帧"的修复，**必须先有实测数据**，才能写 fix task md。

---

## 诊断门控铁律（协调端执行）

| 步骤 | 协调端动作 |
|---|---|
| 收到性能问题反馈 | 要求 Dev 运行 `/perf-diagnose` skill，产出诊断 handoff |
| 收到诊断 handoff | 检查：① 含实测数值（ms/fps/MB）② 含截图或 trace 路径 ③ top-3 来自工具数据而非推断 |
| handoff 合格 | 写 fix task md，必含"诊断数据"段 |
| handoff 不合格 | 退回，要求补实测数据 |

---

## 全平台工具能力矩阵

| 诊断维度 | iOS 工具 | iOS 自动化 | Android 工具 | Android 自动化 |
|---|---|---|---|---|
| CPU / 调用栈 / 火焰图 | Instruments Time Profiler | `xcrun xctrace --template 'Time Profiler'` | Studio CPU Profiler → Flame Chart | `adb shell perfetto` |
| 滚动帧率量化 | Instruments Core Animation | `xcrun xctrace --template 'Core Animation'` | gfxinfo framestats | `adb shell dumpsys gfxinfo framestats` |
| UI 框架重渲 | Instruments SwiftUI Profiler | `xcrun xctrace --template 'SwiftUI'` | Layout Inspector / Perfetto | `adb shell perfetto` |
| 启动时间 | Instruments App Launch | `xcrun xctrace --template 'App Launch'` / `devicectl --measure-launch-time` | adb Displayed / am start -W | `adb shell am start-activity -W` |
| 内存分配 | Instruments Allocations | `xcrun xctrace --template 'Allocations'` | Studio Memory Profiler | `adb shell dumpsys meminfo` |
| 内存泄漏 | Instruments Leaks | `xcrun xctrace --template 'Leaks'` | LeakCanary | `adb logcat LeakCanary` |
| 主线程 IO | Instruments File Activity | — | StrictMode | `adb logcat \| grep StrictMode` |
| 网络瀑布 | Charles / Proxyman | `idevicesyslog` 辅助 | Charles / Studio Network | `adb logcat OkHttp` |
| 视图层级 | Xcode View Debugger | `devicectl captureScreenshot` | Layout Inspector | — |
| 过度绘制 | — | — | GPU 渲染条形图 | `adb setprop debug.hwui.overdraw show` |
| 生产监控 | MetricKit | — | Android Vitals | — |

---

## 两种诊断模式

### 🔧 手动（GUI）模式

适合：深度分析、需要交互式探索、首次定位问题

- iOS：Instruments 系列（Time Profiler / Core Animation / SwiftUI / Allocations / Leaks / App Launch）
- Android：Android Studio Profiler（CPU / Memory / Network）+ 开发者选项可视化工具

### ⚡ 自动化（终端）模式

适合：快速量化、不方便打开 IDE 时的快速诊断

- iOS：`xcrun xctrace record --template '模板名' --attach-by-name {AppName} --time-limit 15s`
- Android：`adb shell dumpsys gfxinfo framestats` / `adb shell perfetto` / `adb shell am start-activity -W`

**两种模式不互斥**：自动化先跑出数值，GUI 工具深入分析根因。

---

## 问题类型 → 优先工具映射

| 问题类型 | 首选组合 | 快速自动化 |
|---|---|---|
| 滚动卡顿 / jank | CPU 火焰图 + 帧率量化 | iOS: xctrace Time Profiler；Android: gfxinfo + Perfetto |
| 启动慢 | 启动时间 + 启动火焰图 | iOS: xctrace App Launch；Android: am start -W |
| 内存增长 | 内存分配 + 泄漏检测 | iOS: xctrace Allocations；Android: dumpsys meminfo |
| 网络慢 | 网络瀑布 | 两端：Charles（手动）+ logcat 辅助（自动）|
| 动画掉帧 | 帧率 + UI框架重渲 | iOS: xctrace Core Animation；Android: gfxinfo + GPU bar |
| 视图过度绘制 | 视图层级工具 | Android: debug.hwui.overdraw |

---

## 诊断 handoff 格式（Dev 必须输出）

路径：`.ai-workspace/handoff/YYYY-MM-DD-{slug}-diag.md`

```markdown
# 性能诊断报告：{问题简述}

## 问题类型
- [ ] 滚动卡顿  [ ] 启动慢  [ ] 内存  [ ] 网络  [ ] 动画

## 实测数据

| 指标 | 数值 | 工具 |
|---|---|---|
| [帧率/耗时/内存等] | X [ms/fps/MB/%] | [工具名] |

## top-3 耗时来源（实测，非推断）

1. **[具体方法/接口/操作名]** — X[ms/fps]（占 X%）
   证据：`.ai-workspace/diag/{slug}-{tool}.png` 或 `.trace`
2. ...
3. ...

## 排除项（实测证伪的候选）

- [候选 A]：实测 Xms 占比不显著 → 排除

## 建议 fix 方向（有数据支撑）

1. [fix 方向]：预期改善 ~X[ms/fps]

## 截图 / trace 清单

- `.ai-workspace/diag/{slug}-flame.png`
- `.ai-workspace/diag/{slug}-network.png`
```

---

## fix task md 必含"诊断数据"段（协调端写 fix 前检查）

```markdown
## 诊断数据

> 诊断报告：`.ai-workspace/handoff/YYYY-MM-DD-{slug}-diag.md`

| top 耗时来源 | 实测值 | 工具 |
|---|---|---|
| [函数/接口名] | Xms | Instruments / Studio Profiler |

预期改善：从 ~Xs 降到 ~Ys（约 -Z%）
```

缺此段 = fix task md 不合格，不派。

---

## 协调端自检（写 perf fix task md 前）

- Q1: 诊断 handoff 含"实测数值 + 截图/trace 路径"？否 → 退回要求补
- Q2: top-3 耗时来自工具（Profiler/抓包），而非代码阅读推断？否 → 退回
- Q3: fix task md 的"预期改善量"有数据支撑？无 → 留空等复测填

---

## 禁止行为

- ❌ 接受星级置信度（⭐⭐⭐⭐⭐）作为诊断证据
- ❌ 接受 NSLog / `System.currentTimeMillis` 打点作为完整诊断
- ❌ 自行添加防御性 sleep/debounce/delay 参数（未经实测支撑）
- ❌ 没有诊断 handoff 就写 fix task md（哪怕"感觉很明显"）
- ❌ 看代码推断根因而不运行工具
