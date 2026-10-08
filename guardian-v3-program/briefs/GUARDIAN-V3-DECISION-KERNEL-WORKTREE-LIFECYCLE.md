---
scheme_id: SULDE-V3-DK-WTL-20260828
title: Guardian V3 Decision Kernel and Worktree Lifecycle Phase 1
status: FROZEN
intent_id: guardian-p0-supervised-delegation-20260815
intent_revision: 162
provider: codex
task_branch: task/guardian-v3-decision-kernel
task_base: dev@762438e5265f8b5dcb1cf9f5653f4fa03e1ac4ed
rollback_source: main@265c5473fac6caf823ff9882e302b589d93840b6
frozen_at: 2026-08-28
---

# Guardian V3 Phase 1 冻结方案

## 1. 结果与边界

本阶段修复 Guardian 把正常 Git worktree 生命周期误判成通用 `.git` 写入的问题，并把
策略结果从相互污染的布尔字段升级为正交 `DecisionV2`。候选只在仓库内
`.worktrees/guardian-v3-decision-kernel` 实施；通过验收后 fast-forward 合入 `dev`，只从
验收通过的 exact dev commit 事务安装。`main@265c547` 和主工作树已有 `.ua` 修改保持不动，
本轮不把 dev 合入 main，不 push，不手改安装 cache、active intent 或 effect ledger。

Phase 1 支持两个不能互相替代的 Git 生命周期能力：

```text
git worktree add <absent-repo-local-target> <existing-local-task-branch>
  -> capability: git.worktree.attach_existing

git worktree add -b <new-task-branch> <absent-repo-local-target> <existing-local-base>
  -> capability: git.worktree.create_branch
```

第一种对应原始故障：任务 branch 仍存在、旧 worktree 已删除，需要恢复同一 branch 的独立
worktree；它不得偷偷创建或移动 branch。第二种对应正常的新任务初始化；它不得覆盖已有
branch。两个 capability 都不支持 `--detach`、`--orphan`、`--force`、相对路径逃逸、已有
target、远程 base、worktree remove/prune/move/repair 或通用 `.git` 写入。

## 2. 已确认基线

- task worktree：`task/guardian-v3-decision-kernel@762438e`，创建后 clean。
- dev：`762438e5265f8b5dcb1cf9f5653f4fa03e1ac4ed`，实施前 clean。
- main：`265c5473fac6caf823ff9882e302b589d93840b6`；主工作树仅保留用户已有
  `.ua/fingerprints.json`、`.ua/knowledge-graph.json`、`.ua/meta.json` 修改。
- 安装前生产 generation：必须在安装阶段重新独立读取并冻结；本文件不把历史读数冒充
  安装时世界状态。

## 3. DecisionV2

`DecisionV2` 是不可变、可序列化的策略值；各维度不能互相推导：

```text
DecisionV2 {
  dispatch: allow | deny | defer,
  would_dispatch: allow | deny | defer,
  lifecycle: continue | pause,
  authority: none | task | continuation | human_grant,
  verification: none | required,
  evidence_state: observed | gap,
  severity, reason, fingerprint, pause_class
}
```

硬不变量：

1. PreTool 对一个不合规调用的普通拒绝是
   `dispatch=deny,lifecycle=continue,verification=none`；它不得创建 pause 或 effect debt。
2. 只有语义漂移、安全完整性失败或已存在适用 pause 才能返回 `lifecycle=pause`。
3. `verification=required` 只表示动作已获准 dispatch 或 completion 已表明效果可能发生；
   `dispatch=deny` 的 PreTool 不能产生 verification debt。
4. `evidence_state=gap` 不等于 deny，也不等于成功；它只表示需要继续收证据。
5. shadow/off 只改变实际 dispatch，不抹去 `would_dispatch`，也不能放松 destructive、
   external 或安全/语义 pause。
6. 旧调用方继续接收只读兼容属性 `action`、`would_action`、`pause`、
   `verification_required`、`observation_gap`；兼容层从 V2 映射，策略核心不再反向依赖旧字段。

## 4. WorktreeLifecycleResource

新的资源身份必须在 dispatch 前绑定以下事实：

```text
WorktreeLifecycleResource {
  operation,
  repository_root,
  common_gitdir,
  common_gitdir_identity,
  worktrees_root,
  target_path,
  target_parent_identity,
  branch_ref,
  base_ref,
  base_oid,
  primary_worktree,
  dev_worktree,
  primary_status_sha256,
  dev_status_sha256,
  branch_state,
  branch_checked_out,
  target_absent,
  resource_id
}
```

分类器只做只读证明：仓库与 `.worktrees` 是 canonical、非 symlink；目标是 `.worktrees`
直接子目录且尚不存在；branch 通过 Git 自己的 ref-format 校验且不是 `main/master/dev`。
`attach_existing` 要求该本地 branch 已存在、解析到固定 commit 且未被任何 worktree 使用；
`create_branch` 要求新 branch 不存在，base 是已存在的本地 branch 并解析到固定 commit。
同一 common gitdir 的 worktree 列表不得冲突。primary/dev/base worktree 是否 dirty 不影响
这两个动作，因为它们消费的是 ref/OID，不读取或修改其他 worktree 的 index/worktree 内容；
分类器冻结 primary/dev status digest，verifier 证明它们未被动作改变，base ref/OID 也必须在
dispatch 前后保持一致。

执行权只覆盖 Git 为这一精确 attach 必然产生的内部后果：新 branch ref、
`.git/worktrees/<generated-id>`、目标 `.git` 反向指针和目标文件 checkout。它不生成可供其他
Git 命令继承的 `.git` allowlist。

独立 verifier 必须重新读取 `git worktree list --porcelain`、target `HEAD`/branch、
`--git-common-dir`、dev/base ref 与 cleanliness，证明：

- target 正好登记一次并绑定目标 branch；
- attach 后 branch OID 未移动；create 后新 branch OID 等于 frozen base OID；target HEAD 等于
  frozen base OID；
- target 的 common gitdir 等于原仓库；
- primary/dev status digest 未改变，base ref 没有移动；
- 新 target clean；main branch/OID 和主工作树内容不作为执行前置，也不得被改变。

## 5. 生产热路径

1. 命令 parser 在 legacy `.git` fallback 之前分别识别 exact attach/create argv。
2. 事件输出 `effect=local_write`、对应的 `git.worktree.*` capability、
   `target=<exact target>`、`write_targets=[<exact target>]` 和 classified typed resource。
3. path policy 使用目标 worktree 路径；`.git` 只是受 verifier 限定的实现后果。
4. malformed/broad/force/existing/outside/release-branch 形式 fail-closed：PreTool deny，
   `pause=false`，零 effect debt，且不得退化成 ordinary unknown/shadow allow。
5. task proposal 明确包含目标路径和 `local_write` 时允许 dispatch；attach/create 的授权互不
   替代，也不跨 target、branch、base OID、session、task epoch 或下一次使用。
6. `success=false` 的 completion 不运行成功态 verifier，但必须继承同一 PreTool 的 sealed
   verification binding、关闭 open event，并把未发生或无法证明的结果保留为可见 effect debt；
   不得留下幽灵 open event，也不得伪造 PASS。
7. 宿主事件同时存在会话 `cwd` 与工具局部 `cwd/workdir` 时，以工具局部执行目录为准；相对
   写目标在进入路径策略前绑定为该目录下的绝对路径。不得用 main 的同名相对文件替代 linked
   task worktree 中真正被暂存或修改的文件。

## 6. 验收矩阵

正例至少覆盖：attach 已有未检出 branch、create 新 branch、相对目标、绝对目标、
`git -C <repo>`、branch/base OID 固定、主工作树或相关 base 有无关 dirty 文件。反例
至少覆盖：attach 的 branch 不存在/已检出、create 的 branch 已存在、`--force`、已有 target、target 在
`.worktrees` 外/嵌套、symlink、`..`、main/master 目标 branch、远程或不存在 base、base OID
漂移、动作期间 primary/dev status 漂移、shell composition、额外 option/operand、共享
common gitdir 双写者。

必须通过：

- `tests/test_resource_adapters.py`
- `tests/test_command_policy.py`
- `tests/test_intent_guardian.py`
- `tests/test_sulde_protocol.py`
- `tests/test_effect_router.py`
- `tests/test_sulde_state_machine.py`
- 相关 release inventory、stage/install preflight 和 failure injection

所有 deny 正例必须断言 `pause=false`，且事件/ledger 中没有新增 verification/effect debt。

## 7. 合入、安装与回滚

1. task diff、scoped tests、failure injection 和 evidence 通过后，用受控 Git lifecycle
   entrypoint 提交 task branch，并 fast-forward 合入 clean dev。
2. 在 exact dev merge commit 上运行集成与 release 前置；任一失败停止安装。
3. 安装前冻结 `main@265c547` 官方 stage/artifact、当前 installed generation、scheduler 与
   launcher 状态；冻结失败则不安装。
4. 只从 exact dev commit 依次运行官方 cachebuster、事务 stager/installer、
   scheduler/launcher reconciliation；独立核对 source tree、artifact、installed runtime、
   manifest version 和 generation。
5. 新 generation 必须通过真实 Codex SessionStart、UserPromptSubmit、PreToolUse、PostToolUse
   canary，以及 worktree attach 正例和危险反例。synthetic callback 只能做前置，不是 live
   验收替代品。
6. 安装或 live canary 失败：停止新写入，保持 main 不动，使用冻结的 main 官方产物事务
   回装，再核对 generation、scheduler、launcher、doctor 和真实只读 Hook canary。

## 8. 失败终态与沉淀候选

任何未通过项保留为可见 finding，不把 inconclusive 写成 PASS，不手工清 ledger/cache，不用
shadow/unknown/低级 Git plumbing 绕过。当前已确认的两个根因是：

- Git 内部 metadata 后果被错误提升成通用 `.git` 内容权限；
- lifecycle provision 把无关 primary worktree dirty 状态错误纳入安全前置。

沉淀候选证据状态为 `confirmed`。协调端后续按单写者规则判重；本任务不直接写知识库。
