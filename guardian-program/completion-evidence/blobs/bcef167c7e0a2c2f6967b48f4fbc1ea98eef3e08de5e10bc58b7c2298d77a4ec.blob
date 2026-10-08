# T00 — 统一控制面实现报告

## 任务与基线

- Task: `T00-control-plane`
- Baseline: `34dcbd0d6ea81ba330c701bc755f1f557978f515`
- Requirement: `PROGRAM-GOVERNANCE`
- Owner / single writer: `guardian-coordinator`
- 状态：实现、定向验收与最新 SHA 独立复审完成；等待证据登记和阶段迁移。

## 已实现

- 不可变 manifest 与逻辑追加、SHA-256 链式事件日志；每次事件通过同目录临时文件、
  `fsync` 与原子替换提交，不留下半行尾。
- owner-only coordinator capability；worker 报告只能由受控单写者登记，worker 不能自行
  进入 `task_verified`、`integrated`、`system_verified`、`accepted` 或完成 program。
- 完整 task 状态机、依赖、唯一 successor、路径所有权和 finding disposition/obligation。
- 每次进入 `running` 生成 coordinator-issued verification run、epoch 与 evidence floor；
  reopen 后旧实现证据不能复用。
- 强类型 evidence v1：baseline、run、verdict、命令退出码、artifact digest、finding、
  requirement 与逐条 acceptance fact 均有绑定。
- 活动证据身份冲突会阻断；恢复只能走单调、语义保持的显式 supersession。
- completion 使用 `prepared → immutable content-addressed snapshot → program_completed` 两阶段
  协议；源报告后续漂移不改变已签署完成事实，快照损坏投影为可查询 integrity blocker。
- final gate 动态重验 accepted task、terminal successor、rejected finding、transferred
  obligation、逐条 requirement acceptance 和 program-level evidence。

## 发现与处置

权威逐项记录位于 `guardian-program/events.jsonl`。本任务共登记 `F00-001` 至 `F00-045`：

- `F00-001`, `F00-003..012`：解决 append 前后验证不一致、伪证据、重复 finding resolution、
  actor 字符串冒充、依赖绕过、空转 transfer、初始化/证据漂移自锁、superseded 终态和 JSON
  布尔类型问题。
- `F00-013..024`：解决 unsupported current-head 事件毒化、completion TOCTOU、多级 successor、
  pass/fail 矛盾、并发 handoff、逆向 evidence replacement、finding obligation、旧 generic
  evidence 复用、verified work reopen、post-commit init、baseline/run 与 acceptance-clause 绑定。
- `F00-025..037`：解决普通事件半写、obligation 在 successor 中丢失、completion 幂等重试、
  active evidence 冲突、implemented 漂移、prepared snapshot 恢复、attested gate digest、
  hardlink 边界、readonly publish 崩溃窗口、completion truth、目录 durability 与 finding
  supersession 语义丢失。
- `F00-038..043`：解决 owned-path `..` 别名、替换依赖 stranded、竞争 successor、finding
  channel 歧义、重复 acceptance mapping，以及 reopen 后整套旧证据复用。
- `F00-044..045`：解决大小写/Unicode 等价路径绕过，以及任意 glob 规范化和不完整交集判断；
  所有权语法现只接受精确规范路径或末尾 `/**` 子树。
- `F00-002` 是主守卫 `.codex-agent` 显式授权路径仍被硬拒绝的问题，不属于 T00 文件边界；
  必须在固定基线上的 coordinator-owned 主集成任务登记后 transfer，不能在本任务伪装为已修。

## 变更文件

- `scripts/kb/guardian_program.py`
- `tests/test_guardian_program.py`
- `guardian-program/MASTER.md`
- `guardian-program/manifest-source.json`
- `guardian-program/manifest.json`
- `guardian-program/events.jsonl`
- `guardian-program/task-definitions/T00-control-plane.json`
- `guardian-program/.gitignore`
- 本报告与独立复审报告/证据文档。

## 验证

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -q tests.test_guardian_program`
  - 56 tests, PASS。
- `python3 -m py_compile scripts/kb/guardian_program.py tests/test_guardian_program.py`
  - PASS。
- `git diff --check -- scripts/kb/guardian_program.py tests/test_guardian_program.py guardian-program`
  - PASS。
- 独立状态不变量复核：10/10 PASS；task ownership、dependency/successor、finding channel、
  acceptance mapping、verification run 未发现仍成立的 blocker/high。
- 最新 SHA 最终独立复核：Blocker 0、High 0；exact/末尾 `/**`、大小写、Unicode、父子范围、
  串行依赖矩阵全部通过，10 类禁用 glob 均在 append 前失败。

## 剩余边界

- owner-only 文件与 `0400` 防止协作进程误写，不是对同 UID 恶意进程的 OS 安全隔离；最终
  权威仍需外部安装 generation、scheduler owner 与 live-host canary 共同证明。
- 整个 program 尚未完成；T00 通过只表示控制面可承载后续任务，不能解释为 Intent Guardian
  已修复、已安装或已在真实宿主跑通。
- 事件链没有仓库外的独立锚；整个 owner-only program root 被有权用户删除时仍需备份恢复。
- `guardian_program.py` 是 program-local 控制器而非 Hook 热路径；其后续可维护性拆分属于优化，
  不能替代本 program 对 `intent_guardian.py` 的 `DERIVED-SPLIT` 验收。

## 回滚

T00 尚未修改安装态、scheduler 或 live host。若控制器本身需回滚，应保留当前 program root
与事件链作为审计工件，停止新增事件并回到最后一个已验证源码快照；不得截断、改写或删除
既有事件来伪造状态。
