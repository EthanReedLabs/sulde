# guardian-post-t32-r1 冻结控制面

- 基线：`dev@da8d9f3ee258fd1e76671e3ff13131e41b5c5f83`
- 任务分支：`fix/r1-git-lifecycle-bootstrap`
- 唯一 bootstrap worktree：`.worktrees/r1-git-lifecycle-bootstrap`
- 合同：Intent Guardian revision 139，原生 receipt `f5874ed0c5511bf7c156932d69bc76f5b1ff93a607357283fce3aa26d105dd66`
- 单写者：worktree 内源码开发可独立进行；Git common-dir 写、合并、安装和 live 切换必须串行。

## 冻结工作流

1. R1-0：结构化 Git 生命周期
   - digest-pinned `agent-runtime.py` 提供精确 `provision`、`commit`、`merge`。
   - `.git` 继续永久禁止路径级直接写；元数据变化仅是受控动作的内部后果。
   - provision 绑定仓库、`dev` 基线 SHA、分支和仓内 worktree 路径。
   - commit 绑定任务 worktree、父提交、消息和精确 staged 路径。
   - merge 绑定目标分支、目标/来源 SHA、来源 ref、精确变更路径，并只允许 fast-forward。
2. R1-A：历史 effect / native recovery
   - 无 replay authority 的历史 attempt 只允许 `abort`，禁止 retry/reprobe/真假裁定。
   - 单个损坏 transaction 不得阻断后续已批准 transaction 的恢复。
3. R1-B：completion evidence 权限物化
   - fresh checkout 的 0644 仅在内容与绑定验证通过后物化为 0400；目录收紧为 0700。
   - symlink、非普通文件、硬链接、owner 异常、路径逃逸、摘要/绑定不符均 fail closed。
4. R1-C：集成与发布
   - scoped tests → task commit → dev fast-forward → release-level verification → main fast-forward。
   - 官方安装链刷新 command-effect snapshot/cachebuster；必须做 installed-artifact smoke、doctor 和 live canary。

## 禁止扩张

- 不创建第二个 bootstrap 例外。
- 不加入新的任务编号，不重建已完成的 T31/T32。
- 不使用通用 shell、通用 `.git` 权限、`worktree --force/remove/prune`、非精确 add、非 fast-forward merge。
- 新发现仅进入报告的“沉淀候选/后续候选”，除非它直接阻断上述验收。

## 完成记录

| 工作流 | 状态 | 证据 | 发现/解决 |
|---|---|---|---|
| revision 127 冻结 | accepted | receipt `b158ce…` | 将 Git bootstrap 自锁纳入原 R1，不增加任务 |
| revision 128 路径纠正 | accepted | receipt `dd9049…` | 将不存在的 `.codex-plugin/plugin.json` 纠正为真实 manifest；其他范围不变 |
| revision 129 安装 grant | rejected | receipt `f1ed00…` | 自动 grant 错绑主工作树且会在合并后摘要失效；拒绝后继续 r128 |
| revision 129 发布桥 | accepted | receipt `410b99…` | 只允许当前 15 路径、1 个提交和两次条件式 fast-forward；新运行时安装后失效 |
| revision 130 精确删除 | execution_failed | receipt `972258…` | 人类批准已落账，但旧运行时把 shell `rm` 无条件升级为 destructive，未删除任何内容 |
| revision 131 可恢复隔离/前向修复 | accepted | receipt `84f8c0…` | 以 15 个逐项 `mv` 代替删除，并冻结 5 文件 shell 删除可达性修复 |
| revision 132 任务缓存纠正 | accepted | receipt `3f4f50…` | 补充任务 worktree 的 `scripts/kb` 两个 ignored 纯 bytecode 目录 |
| revision 133 完整枚举纠正 | accepted | receipt `fe98ae…` | 以 main/dev/task 完整枚举补齐最后 2 个目录；三工作树现均为零 |
| revision 134 发布门闭合 | accepted | receipt `158ea1…` | 抽出超限组件、修正 full-clone 测试 fixture 与结构化 Git command-effect 期望 |
| revision 135 pre-commit 隔离 | accepted | receipt `a3b35a…` | 证明字节码由提交 hook 生成；冻结 hook 环境修复、单一回归和 2 个可恢复移动 |
| revision 136 文本边界纠错 | accepted | receipt `b63a55…` | dev 1381 项仅发现新测试缺显式 UTF-8 参数；冻结 2 参数、3 路径普通尾提交 |
| revision 137 正式发布 | partially_executed | receipt `fdcbb3…` | cachebuster 与 manifest-only release commit `a6b8b635` 已闭合；安装在 PreToolUse 前因 tracked-tree grant 自失效被拒，外部状态未改变 |
| revision 138 tree binding 修复 | accepted | receipt `bd3449…` | 冻结 index blob 历史自锁的最小前向修复；只改摘要算法、release inventory 回归和本控制记录，安装留给唯一 r139 |
| revision 139 唯一生产发布 | accepted | receipt `f5874ed…` | 官方 cachebuster、事务安装、15 个 Codex jobs 重载和 live 验收均闭合；没有手改 cache/registry/launcher |
| 唯一 bootstrap | verified | worktree/HEAD/branch/clean 三方读回 | 旧 Guardian 无 provision；一次性外部 Terminal 精确建树 |
| R1-0 | task_verified | 真实临时仓库 provision/commit/dev fast-forward 回归通过 | 新增 digest-pinned 结构化 Git 生命周期；修正 linked worktree `.git` 文件假设与 Codex stderr 误判 |
| R1-A | task_verified | historical abort/native preview/recovery 回归通过 | 无 replay authority 仅允许 abort；单个损坏事务不阻断后续恢复 |
| R1-B | task_verified | fresh checkout 0644→0400/0755→0700 与 two-phase 失败回归通过 | 先全量验证再收紧，摘要漂移时零权限变化 |
| R1-C | verified | r138 dev full 1383/1383（6 skip）、launcher 23/23、release inventory 9/9；生产代际 `0.2.5+codex.20260825054856-106736206d`；scheduler 15/15；operational readiness ready | 安装、live hook、原生配对、effect debt、model-dispatch、Git lifecycle 与 historical abort canary 全部闭合；最终文档提交后按 task→dev→main 快进 |

详细证据和沉淀候选见 `guardian-post-t32-r1/report.md`。
