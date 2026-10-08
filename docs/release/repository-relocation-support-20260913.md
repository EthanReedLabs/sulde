# Repository relocation support — 冻结控制清单

状态：用户要求先合并清理，迁移实现已停止；本文件仅作未实施计划和清理记录归档，
不可用于真实改名，不构成迁移功能验收通过。capability_tier: deep。

## 目标和边界

用户要求本地仓库、GitHub 仓库、remote 和有效引用统一改为 sulde-pro，已额外同意
先补齐整体仓库迁移支持。本开发阶段基于 dev 71c7d249411b8b5ed2edaa01b8b7d72de81bbb19，
仅新增必要迁移实现、接线、回归和本报告；不实际移动源仓、不改 GitHub、不安装生产。
不以相同 HEAD/remote 替代物理 Git 身份；不删除旧 common-dir 校验；不重写历史账本。

开发批准 receipt：9d767036d2c65c09836ef90c7d0fa01f9c05c108904ed9f8806622637b48f29d。
当前 worktree handoff：7d6260d86bb5fb937c80c3c1c2a0ea83202f05d7cda497e3d2d7c1da3eb20f60。

## 原迁移验收清单（全部未完成，保留而非改写成通过）

- [ ] R1：迁移前源/目标、物理 Git 身份和完整 linked worktree 清单冻结；别名、跨设备、
  目标已存在、外部 worktree、未闭合效果和并发漂移在首次写入前拒绝。
- [ ] R2：当前会话原生审批、会话映射/合同迁移接线；不转移旧任务授权，不允许伪造回执。
- [ ] R3：迁移中断恢复、部分完成识别、幂等终态；历史账本字节不改。
- [ ] R4：真实临时 Git 主仓和 linked worktree 红绿回归、保留未提交文件、clone 冒充、
  路径/身份漂移、原生 Allow/Deny 和恢复负例；相关集成回归通过。
- [ ] R5：报告与证据归档、仅合 dev，完成本开发 worktree 官方 release/finalize 清理。

后续原有步骤（不是本轮已完成）：官方发布安装 → 精确真实迁移卡 → 统一改名与总验收。
出现超出上述实现范围的缺口，记录证据和影响，不静默增加工作流。

## 既有事实

当前仓库为 EthanReedLabs/sulde-cc-pro，管理员权限已核验，目标名查询返回 404。
主仓有六个 linked worktree，全部关联 worktree 干净；main 有用户 .ua 与 .sulde 改动。
已有进程占用旧目录，真实移动前必须重新核对并协调静默窗口，不能以本次快照代替。
已安装版本与 dev 的 recovery/session_workspace 字节一致，common-dir 路径限制确实存在。

KB 首轮症状检索偏向无关移动端缓存，未采纳；换症状检索命中
work-model/git-worktree-content-evidence-materialization 并全文回读，采用物理身份、
工作树/index/提交分层证据纪律，不把 Git 0400 当可移植属性。

## 2026-09-13 用户改令：合并与清理

当前会话原生批准清理 revision 3，receipt：
`d1c1a77e414451e60c0828e4d8caa399374176fea14d10e7b99f95ad2dd282ab`。
本次只归档文档、保全证据和清理已合并资源；没有写入迁移实现或测试代码。

### 已核验并删除的旧资源

| worktree / 本地分支 | 冻结 HEAD | 结果 |
|---|---|---|
| public-harness-export / task/public-harness-export | ab3eef2223c273a4e9bc06e31018b2661182e40b | 已为 dev 祖先；干净；证据保全后普通 Git remove 和 branch -d 成功 |
| sediment-guardian-consistency / feat/sediment-guardian-consistency | e921807a4a4d8aeb1ff08631d2840974f20f9f8a | 已为 dev 祖先；干净；证据保全后普通 Git remove 和 branch -d 成功 |
| 无 worktree / task/sediment-guardian-publication | e61683c | 已为 dev 祖先；branch -d 成功 |

删除前 `git merge-base --is-ancestor <HEAD> dev` 均 exit 0，两个 worktree 的
`git status --porcelain=v1 --untracked-files=all` 为空。未使用强制删除。
`lsof` 对两个目录的 cwd 检查和各自忽略证据目录的打开文件检查无匹配；
这只是删除前观察，不是永久进程锁。

### 原始证据保全

归档根：dev worktree 下 `.sulde/public-export/cleanup-20260913/`，目录权限 0700，
仅本地保存，未上传；名称中的 public-export 不表示公开授权。

- `public-harness-export-sulde/`：原 worktree 的 `.sulde/`，约 730 MB。
- `sediment-guardian-consistency-sulde/`：原 worktree 的 `.sulde/`，约 1.2 GB。

使用 `cp -a` 保留副本；删除前逐项执行
`rsync --archive --checksum --dry-run --itemize-changes --delete <source>/ <archive>/`，
两次均 exit 0、零输出，未发现内容/符号链接/权限/时间戳或额外文件差异。
其中 `--delete` 只参与 dry-run 差异检测，没有通过 rsync 删除文件。
原始证据内的历史路径未改写，副本不是可重放授权。
工作树源码可从 dev 中保留的上述提交重建，再按需恢复对应忽略证据。

### 保留的三个未合并分支

| worktree / 分支后缀 | 独有提交 | 保留原因 |
|---|---|---|
| release-dev-acceptance | acd562cf875af5a96fbed81a6b88fa6325019abb | 失败验收报告及原始证据；报告明确要求保留、不合并失败候选；后继修复成功不能抹掉原始失败 |
| sediment-floating-tab-clearance | 933461c12be181ab9e36bbbd7331fbe163dd868c | 未合入 dev；与下一分支均修改 ArkUI 页面壳文档、INDEX、MANIFEST 和 CHANGELOG |
| sediment-floating-ui-invariants | 64cc5153885f605003061f96b86971c4f4a038e3 | 未合入 dev；与上一分支重叠，未完成语义去重及组合后的知识库验证 |

三个 worktree 均干净，且各有一个独有提交；本轮不协调改写知识内容、不删除未合并提交。
这不等于断言两个知识分支的原始验证失败，只表示没有本轮组合合并验收证据。

### 当前文档归档收尾

本文件是当前任务唯一新增文件。文档差异检查通过后才提交并快进合入 dev，
不合入任何未实施或中断的迁移代码。随后结束 Skill frames，通过官方
`release-completed-workspace` 释放当前任务、普通 Git 删除当前 worktree/分支，
最后 `finalize-workspace-cleanup` 回读 complete；该回执只证明本次归档清理完成。
本报告写入时这组最终机械动作尚待执行，以实际 Git 状态与完成回执为准。

本轮不运行代码测试：不存在运行时代码变更，检查范围为文档、Git 祖先关系、
证据副本与资源清单，不把这些检查标成迁移功能测试。
main HEAD 保持 bd216b3d29e37b1aaf0e6be0c930b5221a925562，用户三项 `.ua` 改动和
未跟踪 `.sulde/` 保留。不推送、不安装、不改 GitHub 或 remote、不移动仓库根。

## 发现与沉淀候选

复用既有“工作树、提交和证据分层”纪律：Git status 干净且提交已合并，仍不能证明
忽略的验收证据已归档。本轮实际发现两个已合并 worktree 内约 1.9 GB 忽略材料，
已保全并校验后清理。没有产生新的迁移修复根因或独立 Layer2 知识条目，不写共享 KB。
