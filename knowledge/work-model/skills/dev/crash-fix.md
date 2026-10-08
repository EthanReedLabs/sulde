---
doc_id: "work-model/skills/dev/crash-fix"
container: work-model
platform: cross
summary: "Android/iOS Dev 以四阶段证据链完成崩溃(含 native/tombstone)、无响应与编译错误的最小修复。"
---

# 崩溃快速修复（Android / iOS）

用于运行时崩溃、编译失败、Android ANR 与 iOS watchdog。目标是先保存现场，再按"症状→候选根因→排除→最小修复"闭环；不自动 commit。

## 启动门控

先确认来源：运行日志、build、无响应、用户粘贴的堆栈或崩溃平台报告。记录复现步骤、环境、版本、发生频率与最近一次正常 baseline。缺少现场时只诊断，不猜修复。

## 四阶段诊断

1. **症状提取**：异常类型、首个业务栈帧、线程、触发页面与状态链路。
2. **根因列举**：至少三个候选，区分逻辑、配置、依赖、时序、生命周期和内存问题，按概率排序。
3. **根因排除**：读取崩溃点上下文与调用方；用历史改动、复现和反证逐个排除。`git log/blame` 只用于定位变化与责任域，不用于点名个人。
4. **修复方案**：选择最小且触及根因的改动，检查是否掩盖上游契约、制造静默失败或破坏其他状态；用户确认后实施。

## 平台采集与分析

### Android:

- 运行崩溃：保存 `adb logcat` 的 `AndroidRuntime`、业务进程日志与完整 cause chain；zsh 下 `'*:S'` 必须加引号。
- native 崩溃（tombstone，含 GPU/驱动类）：logcat 无 `AndroidRuntime` 栈、只有 tombstone（含 `signal`/`backtrace` 段）时按三步走：
  1. **先隔离非目标加载路径**：排除与目标无关的加载源（典型如应用启动阶段的急切预加载），确保崩溃只能由目标路径触发，避免多条加载路径混叠导致归因错误。
  2. **加自动运行入口使复测可重复**：提供 adb 可直接触发的自动运行入口（如启动参数/专用调试入口），让目标路径每次复测一致且可脚本化，而不是依赖手工点击操作序列。
  3. **符号化 tombstone 定位源码行**：用未 strip 的 .so 配合 `llvm-addr2line`（NDK 自带）把 tombstone 中崩溃地址（backtrace 各帧 pc + so 相对偏移）转成源码文件与行号；符号化用的 so 必须与设备上崩溃的包出自同一次构建。
  - GPU/驱动相关信号：帧落在厂商 GPU 驱动库或图形栈 so 内。此时四阶段照常执行，但证据采集以 tombstone 符号化结果为准。
- ANR：采集 traces 或 bugreport，同时保留主线程、锁等待、Binder 与系统负载证据。
- build：执行最小模块的 Gradle 编译任务，保留首个编译错误及其上下文。
- 环境：设备型号、Android/API 版本、应用版本。
- 状态链路：检查 Activity/Fragment → Store → Intent/Action；审查 reducer 分支、unsafe cast、空值强制解包和 Command/Result 覆盖。

### iOS:

- 模拟器：优先读取 DiagnosticReports；必要时用 `xcrun simctl spawn booted log stream` 保存实时日志。
- 真机：从 Xcode Devices、`devicectl` 或已导出的 crash report 获取报告，先符号化再归因。
- build：执行目标 scheme 的 `xcodebuild`；SPM 问题单独保留解析错误。
- 环境：设备/模拟器、iOS 版本、Xcode 版本、应用版本。
- 状态链路：检查 View → Store → Action/Effect；重点审查 TCA state 可选值、effect 生命周期、主线程约束、数组越界、未处理 Objective-C exception 与 watchdog。

## 责任路由

按首个可行动业务栈帧映射到模块 owner（某端 Dev）。跨模块时由崩溃点 owner 主责，上游契约 owner 协查；不要把系统库顶层帧误判为责任模块。

## 修复与验证

- 只改根因相关代码，不顺带重构。
- 防御性检查必须有可观察失败路径；不能用吞异常替代契约修复。
- 修前把原始日志、复现条件和环境写入本端报告或 handoff。
- Android: 跑最小 Gradle compile/test，并在同类设备复现路径验证。
- iOS: 跑目标 scheme build/test，并在对应模拟器或真机复现路径验证。
- 对照 baseline，确认崩溃消失且关键业务状态、返回路径和三态视图无回归。

## 报告模板

```markdown
# 崩溃报告
- 平台/环境：
- 复现步骤与频率：
- 异常类型 / 首个业务栈帧：
- 状态链路：
- 候选根因与排除证据：
- 最终根因：
- 责任域：某端 Dev / 模块
- 最小修复：
- 验证命令与结果：
- 回归风险：
```
