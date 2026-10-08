# LIFE-P0 — runtime 主链与隔离执行器修复

## 目标

完成 P0 修复，使 mem-sync 调度不再因共享 Git 仓库并发、生成文件污染或错误上游参数而退化；同时修复 `agent-runtime.py provision` 因无关主工作区脏文件而拒绝创建独立任务 worktree 的自锁。

## 已知事实

- 基线：`815e7e5b66842194cbef9b102dc1c0039a29c446`。
- `com.sulde.mem-sync-import` 最近退出码为 2。
- 生产日志反复出现 `git pull --rebase --autostash` 的“无法变基到多个分支”，并与生成的 `*.edges.jsonl`、`*.entities.jsonl`、主 JSONL 和 `manifest.json` 冲突。
- `/Users/eric/.sulde/data/kb/mem-sync.json` 的 repo 仍指向 Claude 用户目录；实现不得依赖 Claude CLI、Claude MCP 或 Claude 用户目录。
- `agent-runtime.py provision` 会先要求 primary worktree clean，导致 main 中与任务无关的用户 `.ua` 修改阻断从 clean dev 基线创建隔离 worktree。
- Guardian 会直接拒绝在新 worktree 创建 `.codex-agent` brief；执行器任务准备路径不能因此自锁。

## 必须实现

1. mem-sync 使用 Sulde 独立的数据/仓库根；兼容迁移必须明确、幂等、可回滚，不能把 Claude 路径作为正常依赖。
2. import/export 对共享同步仓库使用同一把跨进程锁；同一时刻只允许一个 Git 事务。
3. Git 上游只能是一个经校验的 remote/ref，不得形成多分支 pull；生成文件不得以未提交状态污染下一轮同步。
4. 事务失败保留原始事实，后续可重试；不得把失败写成成功。
5. 调度入口采用有界重试/退避，人工与 scheduler 路由语义分别报告。
6. `agent-runtime.py provision` 只校验拟作为基线的 ref/commit 和目标 worktree，不因另一个物理 worktree 的无关脏文件失败；仍须拒绝目标路径冲突、基线漂移和共享 Git 元数据异常。
7. 为执行器任务准备提供受控、可审计且不依赖绕过 Guardian 的路径；不得放宽普通控制工件保护。
8. 不改阈值、不删除账本、不扩大权限、不触碰 main/dev 或正式安装。

## 测试与证据

- 增加并通过 mem-sync 并发、单上游、脏生成物、失败恢复、幂等迁移回归。
- 增加并通过 provision 正例：primary 有无关脏文件但 exact dev 基线 clean 时可创建；反例继续拒绝目标冲突、错误基线或目标不洁。
- 增加任务准备的正反例；仍拒绝伪造或越界控制工件。
- 运行精确受影响测试；只有跨多个主模块或改变安装/调度协议时才扩大到相关组合测试，不无条件跑全量。
- 输出变更摘要、测试命令与结果、剩余风险、沉淀候选。不得提交、合并、推送、安装或删除 worktree。

## 允许修改

- `scripts/kb/mem-sync.py`
- `scripts/kb/agent-runtime.py`
- `scripts/kb/life-cycle.py`
- `scripts/kb/operational_readiness.py`
- `scripts/kb/install-agents.sh`
- `scripts/kb/intent_guardian.py`
- `scripts/kb/intent_guardian_parts/**`
- `templates/launchagents/com.sulde.mem-sync-import.plist`
- `templates/launchagents/com.sulde.mem-sync-export.plist`
- `tests/test_mem_sync.py`
- `tests/test_agent_runtime.py`
- `tests/test_life_cycle.py`
- `tests/test_operational_readiness.py`
- `tests/test_scheduler_entrypoints.py`
- `tests/test_intent_guardian.py`

若必须修改未列出的文件，停止并在报告中说明，不得自行扩面。
