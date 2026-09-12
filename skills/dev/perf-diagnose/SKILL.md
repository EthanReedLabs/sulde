---
name: perf-diagnose
description: 性能诊断 / 慢 / 卡 / 延迟 / 优化 / 提速 / 卡顿 / jank / lag / 为什么这么慢 / 进场慢 / 加载慢 / 响应慢 / 抖动 / 掉帧 / 内存 / OOM — 在写任何 fix 之前先用工具测量,产出多维诊断报告。当用户或 Dev 说"慢/卡/延迟/优化/提速/卡顿/抖动/掉帧"时自动触发。禁止跳过直接猜根因。stack 中性 — profiler 命令 / 指标阈值 / 平台模式从 references/{stack}.md 读。
user-invocable: true
---

# 性能诊断(Measure First 强制)

**核心原则:Measure First,禁止 Guess First。**

在产出任何假说或 fix 建议之前,必须先用工具测量。诊断 skill 只产出**带实测数据的诊断报告**,**不写 fix**(fix 由协调端 review 诊断报告后另行派 task)。

**stack 决定后必先 Read 对应 references**(profiler 命令 / 指标阈值 / 平台特定模式全在那里):

| Frontend stack | 必 Read |
|---|---|
| `mobile-android` | `references/android.md` |
| `mobile-ios` | `references/ios.md` |
| `mobile-flutter` | `references/flutter.md` |
| `mobile-harmony` | `references/harmony.md` |

> 完整 SOP 见 `<docs-hub>/00_shared-rules/perf-diagnosis.md`(若项目有三端共享真值)

---

## §1 perf-gate 触发词(自动激活)

以下词命中任一即必须走本 skill,不许跳过直接给 fix:

```
慢 / 卡 / 延迟 / 优化 / 提速 / 卡顿 / 抖动 / 掉帧 / jank / lag
进场慢 / 加载慢 / 响应慢 / 启动慢
内存增长 / OOM / 内存泄漏
为什么这么慢 / 性能差 / 体验差
```

**判定线**(违一即不合格):

- ❌ 接受"假说星级 ⭐⭐⭐⭐⭐"作为诊断证据
- ❌ 没跑 profiler 就写 fix 建议
- ❌ 自加"防御性 sleep / debounce / delay"未经实测
- ❌ 仅靠 `System.currentTimeMillis()` / `NSLog T0~T4` 打点当完整诊断数据
- ❌ 跑完 profiler 顺手写 fix(诊断和 fix 必须分开 — 见 §7)

---

## §2 思考模式(强制)

**执行 `/perf-diagnose` 时必须启用 think hard 深度思考**。性能问题易被表面症状误导,必用结构化思考:

```
think hard。

角色:资深移动端性能工程师(stack 见 references)

执行流程(5 阶段):

阶段 1【重现 repro】
  - 确认问题边界(滚动 / 启动 / 内存 / 网络 / 动画)
  - 真机型号 + 系统版本
  - 冷启动 vs 热路径
  - 大致严重程度(用户感知描述)

阶段 2【测量 measure】
  - 按问题类型选 profiler(详 references/{stack}.md §2)
  - 跑自动化抓取(优先),GUI 工具作补充
  - 数据归档到 .ai-workspace/diag/

阶段 3【假说 hypothesise】
  - 基于实测数据列出至少 3 个候选根因,按数据支撑度排序
  - 区分:主线程阻塞 / 渲染瓶颈 / 内存增长 / 网络延迟 / 锁等待
  - **严禁星级置信度替代实测**

阶段 4【建议 fix 方向(不写 fix 代码)】
  - 每个候选给"预期改善 ~Xms / ~X%"
  - 标注实施成本与风险
  - 自我批判:数据是否足以支撑?有无遗漏候选?

阶段 5【再测量 re-measure 路径(列给协调端)】
  - 给出 fix 后必须复测的指标 + 工具
  - 给出对比基线(本次测得的 P50/P99 等数值)
```

---

## §3 Step 1:确认问题边界

先问用户(用 AskUserQuestion,同时问):

1. 问题类型(单选):
   - 滚动卡顿 / jank / 抖动(列表不流畅)
   - 启动慢 / 进场慢(点击 → 看到内容)
   - 内存增长 / OOM / 崩溃
   - 网络慢 / 接口超时
   - 动画掉帧(transition / 进出场动画)
   - 其他(描述)

2. 是冷启动还是每次都慢?(或:cache miss 还是 cache hit 都有?)
3. 真机型号 + 系统版本?
4. 大致严重程度(用户感知描述,例:滚 5 秒明显卡 2 次)

---

## §4 Step 2:按问题类型运行诊断套件

**根据 Step 1 答案选对应组合,优先跑自动化方案,GUI 方案作补充或深入分析用。**

各 stack 的工具映射见 references/{stack}.md §2 工具速查表。通用维度:

| 维度 | 通用语义 | 工具入口(详 references/{stack}.md) |
|---|---|---|
| CPU / 调用栈 | 火焰图 / 时间轮廓 | §2.1 |
| 自定义时间线标记 | 代码插桩 + profiler 对齐 | §2.2 |
| 帧率量化 | P50 / P90 / P99 帧耗时 + jank 比例 | §2.3 |
| 帧流水线底层 | 渲染合成层延迟 | §2.4 |
| 启动时间 | 冷 / 温 / 热三态 | §2.5 |
| 启动链路 | pre-main / main / 首帧 | §2.6 |
| 内存分配(JVM / Heap) | 对象数 / retained size | §2.7 |
| Native 内存 | 底层 alloc 来源 | §2.8 |
| 内存泄漏 | retain cycle / 实例数 | §2.9 |
| 主线程 IO 检测 | DiskRead / Network on main | §2.10 |
| 网络瀑布 | DNS / Connect / SSL / Wait / Receive | §2.11 |
| 过度绘制 / 视图层级 | overdraw / 层叠数 | §2.12 |
| 性能回归防护 | 持续 benchmark | §2.13 |

---

## §5 关键指标阈值(stack 通用语义)

各 stack 的具体工具 + 指标读法见 references/{stack}.md §3。通用阈值参考:

| 指标 | 良好 | 警告 | 严重 |
|---|---|---|---|
| P50 帧耗时 | < 8ms | 8~12ms | > 16ms |
| P90 帧耗时 | < 12ms | 12~16ms | > 20ms |
| P99 帧耗时 | < 16ms | 16~25ms | > 30ms |
| Jank 比例 | < 1% | 1~5% | > 5% |
| 主线程最大 spike | < 16ms | 16~50ms | > 100ms |
| 冷启动时间 | < 1.5s | 1.5~2.5s | > 3s |
| 热启动时间 | < 500ms | 500~800ms | > 1s |
| 单次接口延迟(WiFi)| < 300ms | 300~800ms | > 1.5s |
| 内存峰值(中端机)| < 200MB | 200~350MB | > 500MB |

**P99 > 16ms = 用户能感知的 jank**;**Jank 比例 > 5% = 体验严重劣化**。

---

## §6 Step 3:写诊断 handoff

路径:`.ai-workspace/handoff/{YYYY-MM-DD}-{slug}-diag.md`(类型 1 跨终端 handoff)

### §6.1 必含段(缺一即不合格)

```markdown
# 性能诊断报告:{问题简述}

## 问题类型
- [ ] 滚动卡顿  [ ] 启动慢  [ ] 内存  [ ] 网络  [ ] 动画  [ ] 其他

## 环境
- 设备:{型号} / 系统:{版本} / App 版本:{构建号}
- 触发条件:{冷启动 / 列表第 N 屏 / 特定操作链}

## 诊断数据(实测,非推断)

| 指标 | 数值 | 工具 | 截图 / 文件 |
|---|---|---|---|
| Jank frames 比例 | X% (N/Total) | {stack 工具} | `.ai-workspace/diag/{slug}-frames.{ext}` |
| P99 帧耗时 | Xms | {stack 工具} | 同上 |
| 主线程最大 spike | Xms({函数名}) | {stack 工具} | `.ai-workspace/diag/{slug}-flame.{ext}` |
| 启动时间 | Xms | {stack 工具} | `.ai-workspace/diag/{slug}-launch.{ext}` |
| 内存峰值 | XMB | {stack 工具} | `.ai-workspace/diag/{slug}-mem.{ext}` |
| 网络请求 1 | Xms({串行/并行}) | Charles / 抓包 | `.ai-workspace/diag/{slug}-net.{ext}` |
| 响应体大小 | XKB / N条 | 同上 | 同上 |

## Top-3 耗时来源(实测,非推断)

1. **[具体函数/操作名]** — Xms(占总耗时 X%)
   证据:`.ai-workspace/diag/{slug}-flame.{ext}` 主线程最宽块
2. **[操作名]** — Xms / 重渲 N 次/秒
   证据:同上
3. **[接口名]** — Xms
   证据:`.ai-workspace/diag/{slug}-net.{ext}`

## 排除项(列已测但排除的候选)

- [候选 A]:实测 Xms 占比不显著 → 排除
- [候选 B]:profiler 未出现在主线程 → 排除
- [候选 C]:与 jank 时间段不重合 → 排除

## 建议 fix 方向(数据支撑,不写代码)

1. [fix 1]:预期改善 ~Xms(根据 top-1 函数耗时)
2. [fix 2]:预期改善 ~X%(根据 jank 比例)
3. [fix 3]:预期改善 ~XMB(根据内存峰值)

## fix 后复测路径(协调端派 fix task 时引用)

- 复测指标:{P99 帧耗时 / Jank 比例 / 启动时间 / ...}
- 复测工具:{同诊断工具,保证可比}
- 验证阈值:{P99 < 16ms / Jank < 1% / 启动 < 1.5s / ...}
- 基线数值(本次):{填实测数值}

## 截图 / trace 文件清单

- `.ai-workspace/diag/{slug}-flame.{ext}`(CPU 火焰图)
- `.ai-workspace/diag/{slug}-frames.{ext}`(帧率)
- `.ai-workspace/diag/{slug}-launch.{ext}`(启动,如适用)
- `.ai-workspace/diag/{slug}-mem.{ext}`(内存,如适用)
- `.ai-workspace/diag/{slug}-net.{ext}`(网络,如适用)
- `.ai-workspace/diag/{slug}-overdraw.{ext}`(过度绘制,如适用)
```

### §6.2 自检(提交 handoff 前)

- [ ] handoff 含**实测数值**(ms / fps / MB / %),不是"大概"/"感觉"
- [ ] 至少 1 张 flame chart / time profiler 截图或 trace 文件存在
- [ ] Top-3 耗时来源都有工具证据(不是 logcat 打点推断)
- [ ] 帧率指标(Jank 比例 + P99)已记录
- [ ] 排除项列出至少 1 个已测但排除的候选
- [ ] fix 后复测路径已写(指标 + 工具 + 阈值 + 基线数值)
- [ ] 没有绕过测量直接写 fix 代码
- [ ] handoff 路径在 `.ai-workspace/handoff/` 且文件名带 `-diag`

---

## §7 Step 4:告知协调端(不在本 skill 写 fix)

handoff 写完后,回话给用户:

> 「诊断报告已写到 `.ai-workspace/handoff/{YYYY-MM-DD}-{slug}-diag.md`,含实测数据 + Top-3 耗时 + 排除项 + fix 方向建议。请把 handoff 交给协调端,协调端基于诊断数据写 fix task md。」

**本 skill 到此结束。**

**铁律**:Dev 诊断完不直接动手 fix,等协调端审核诊断报告后通过 `/assign` 派 fix task。这避免:

1. 诊断证据不足就改代码,治标不治本
2. 多个 candidate root cause 没充分对比就修了次要的
3. 协调端无法基于诊断报告做跨端反模式登记

---

## §8 与其他 skill 衔接

### §8.1 与 `/crash-fix` 区别

| 维度 | /perf-diagnose | /crash-fix |
|---|---|---|
| 触发 | 慢/卡/延迟(运行正常但慢) | 闪退/异常/编译错误(运行失败) |
| 输出 | 诊断报告(带数据) | 修复代码 + 验证 |
| 后续 | 协调端派 fix task | 直接 commit |

崩溃同时伴随性能问题 → 先 `/crash-fix` 稳定运行,再 `/perf-diagnose` 测性能。

### §8.2 与 `/postmortem` 衔接

fix task 完成后(协调端派的 fix 跑完),协调端必跑 `/postmortem`:

- Q1 这次性能问题以前踩过类似 pattern 吗?(grep 反模式集合)
- Q2 会再踩吗?(同模块 / 同 stack)
- Q3 能不能 lint 化?(eg. 主线程 IO 检测自动化)
- Q4 其他 frontend 也有吗?(跨 stack 复制检查)

诊断 skill 不直接跑 postmortem,但**诊断报告的"排除项 + fix 方向"应足以让 postmortem 提取 pattern**。

---

## §9 反例(禁止)

❌ "感觉是主线程 inflate 太多" → 没跑 Profiler 就写假说
❌ "778 条 label 性能差 ⭐⭐⭐" → 星级置信度替代实测
❌ "fullScreenCover 链重建 ⭐⭐⭐⭐⭐" → 同上
❌ 只用 `System.currentTimeMillis()` / `NSLog T0` 打点 → 只测时间段不显示 CPU 干了什么
❌ 看 SharedPrefs / UserDefaults 内容推断"数据量大性能差" → 不是 Profiler 数据
❌ 跑完 Profiler 顺手写了 fix → 诊断和 fix 必须分开(§7)
❌ 诊断 handoff 没有"排除项"段 → 协调端无法判断诊断完整性
❌ 自加 sleep / debounce / delay 当 fix → 未经实测无法证明有效

---

## §10 示例

```
用户:首页 Feed 滚动卡顿,iPhone 12 上特别明显
助手:/perf-diagnose 启动。先确认边界(AskUserQuestion):

  1. 问题类型?→ 滚动卡顿
  2. 冷启动还是每次都卡?→ 每次进首页滚 5 秒都卡 2 次
  3. 型号 + 系统?→ iPhone 12 / iOS 17.4
  4. 严重程度?→ 用户能明显感知

正在按 references/ios.md §2 跑诊断套件:
  - Time Profiler(滚动 15s)→ trace 文件已存到 .ai-workspace/diag/
  - SwiftUI Profiler → body 重算次数已记录
  - Core Animation → FPS 曲线已抓
  - Memory Allocations → 增长曲线已抓

诊断报告写完:.ai-workspace/handoff/<date>-home-feed-jank-diag.md
  - P99 帧耗时:42ms(警戒线 16ms)
  - Top-1 耗时:`FeedItemView.body` 主线程 35ms × 多次(占总耗时 60%)
  - 排除项:网络请求(不在 jank 时间段)/ 图片解码(已在后台)
  - fix 方向:1. `EquatableView` 减少重算 / 2. 列表 cell 高度预计算

请把 handoff 交给协调端,协调端基于数据写 fix task。
```
