# 遗留分支归档与整合收尾

状态：整合验收通过并已合 dev，三个遗留 worktree/分支已全部归档清理；capability_tier: deep。
当前 Codex 协调端单写者，无并行 Agent。

## 冻结范围

从 dev `ebfccf8b006ec0844d1d20623fdab19091fc6daa` 创建本任务。
原生范围批准：`3bd28781ddc21d3204a8a06ae0b0b56f8d52042161a081741b80a7ed1824fe18`。
worktree handoff：`386c20c9198d02313fb34a08a354dabdf3eb1666780ecae50cae04b423dc2855`。

仅整合两个已有 UI 知识分支、归档失败验收与三个分支的原件、验证后清理。
不执行迁移修复、安装、push、main 合并或源应用操作；不改历史账本和生产索引。
本轮不是新增知识主题，保留原证据状态且不把知识文档的历史验证声明当成本轮设备测试。

## 单一控制清单

- [x] A：冻结三个源 HEAD 和干净状态；Git bundle 可验证，忽略材料完整归档并校验。
- [x] B：两个知识分支无损整合；当前 387 篇保留、编号不冲突、旧约束和四类样本不丢。
- [x] C：frontmatter/sedimentation、索引/manifest、隔离检索与回归通过；不放宽阈值。
- [x] D：仅验证内容合 dev；失败验收只归档，不标通过。
- [x] E1：三个原 worktree/分支已清理，main 用户改动保持。
- [ ] E2：本报告最终提交合 dev 后释放并清理本任务；终态以官方 completion 回执为准。

## 源清单和恢复边界

| 分支 | 原 HEAD | 处理 |
|---|---|---|
| task/release-dev-acceptance | acd562cf875af5a96fbed81a6b88fa6325019abb | 原失败报告/约 91 MB 证据归档；不合并失败候选 |
| feat/sediment-floating-tab-clearance | 933461c12be181ab9e36bbbd7331fbe163dd868c | 保留窄版独有证据限制、反例和 4 条检索样本 |
| feat/sediment-floating-ui-invariants | 64cc5153885f605003061f96b86971c4f4a038e3 | 作为完整知识整合来源，保留 16 条检索样本 |

长期归档在 dev `.sulde/public-export/legacy-branch-closure-20260913/`，根权限 0700，
只用于本地恢复；名称不代表公开/上传授权。Git bundle 保留原提交，忽略材料保留原字节。
任一源漂移、有活动占用或验证失败，则不删除该源。不用旧 INDEX/MANIFEST 覆盖当前 dev。

## 判重与证据

底栏症状检索返回 Android 底栏条目，平台/根因不同，未采纳。
合并治理检索命中 `work-model/lossless-knowledge-dedup`，score 0.890712；全文回读后
采用“同容器同根因并入、治理资产无损保留”的规则。
两个分支同一 ArkUI 页壳文件的 Git 对比直接证明核心预算一致，扩展版不是窄版逐字节超集。
本轮整合将保留窄版的未测范围、失败限制、独立无底栏路由和单设备硬编码反例。

## 验证与执行记录

### 归档验证

`source-branches.bundle` 包含三个原始 refs 和完整历史（无前置提交要求），bundle verify 成功。
另从 bundle 独立 clone 为归档中的 `recovery-verification.git`，`git fsck --full` exit 0，
三个 refs 与冻结 HEAD 完全相同。裸仓默认 master 未出生的 notice 不影响三个命名 refs 恢复。

原始材料分别保留为 `release-dev-acceptance-local/`、
`sediment-floating-tab-clearance-local/` 和 `sediment-floating-ui-invariants-local/`；
失败报告另存 `original-failed-acceptance.md`。三个目录均经
`rsync --archive --checksum --dry-run --itemize-changes --delete` 对照原目录，exit 0、零差异。
该命令始终 dry-run，无 rsync 删除行为。原始材料约 1.4 GB，历史路径不重写。

### 合并发现与处理

- 扩展版与 dev 的冲突仅在 CHANGELOG、总索引、MANIFEST 和反模式索引；保留两方
  changelog 与条目，反模式跨端数量修正为 45，总索引/manifest 从当前 tracked 语料生成。
- 以扩展版为整合来源，补回窄版六组原始正反样本、精确历史证据限制、
  单设备硬编码反例、无底栏路径、背景保留和 `purpose=route` 的消费边界。
  两分支使用同一 doc_id/路径，无需另建重复文档或 tombstone。
- 独立检查原 dev 387 个 manifest 路径全部存在：383 篇哈希不变、4 篇为本次明确更新；
  只新增 ap-0253。窄版 4 条和扩展版 36 条（原有 20 + 新增 16）JSON 用例逐项等于原分支。
- 隔离检索目录复制后已带 venv 符号链接；一次多余的 ln 被文件权限拒绝，未创建
  生产 `venv/venv`，经只读确认后直接使用已有链接。未重试写生产，也未改安装。

### 验收结果

| 检查 | 实际结果 |
|---|---|
| frontmatter lint | 394 个 tracked Markdown，通过 |
| sedimentation lint | 47 个 v2 文档，通过 |
| INDEX/MANIFEST --check | 均通过，388 篇 |
| 隔离索引构建 | 388 docs、1887 chunks、220 edges、missing_related=0；3.28 秒 |
| 官方隔离 runner，7 个相关测试模块 | 37/37，通过，无 skip，1.486 秒 |
| 主独立检索集 | 36/36 满足原 gate；exact top-1 31/36 |
| 窄版独立检索集 | 4/4 满足原 gate；exact top-1 4/4 |
| Git diff --cached --check | 通过；无删除知识文档 |

检索 gate 保持 min-rate=1、top-k=3，skip 必须第一名；没有把非首位命中写成 exact top-1。
所有索引写入限定在本任务 `.ai-workspace/legacy-branch-closure/kb-home`，生产索引不改。
没有再次运行来源应用的设备/动画测试，也没有执行全量 Guardian 发布验收。

归档证据 SHA-256：

| 文件 | SHA-256 |
|---|---|
| source-branches.bundle | 8dc738e84811a052de4a6258af51deac7d40c2fb47802f46cc30868d8d3a0811 |
| original-failed-acceptance.md | 9826f47c4d81f9437cc70914f2b1aea92976ded21bece1579fea055d23c36d25 |
| retrieval-main.json | b99731ee2ca360e10725a0b72af562acc32aa9c6be72449e30d681ff6e3f92fb |
| retrieval-narrow.json | efe4596c5f33c775900306b20ed23b8139e01acd78167fd8d13df18854410375 |
| scoped-tests.log | ac6f35e8cb5b32d5c64070d23194f58a1adf0fc55686af33e580dad90345d454 |
| index-build.log | 099ef0808a23ecbed307bb5eced088d30aeb22ad142a422079cf1ae51a24c4dc |

## 沉淀候选：Layer1 收尾记录

- 问题类型：workflow；目标是结束遗留分支但不丢知识或失败历史。
- 已确认根因：并行知识分支从旧语料生成索引，直接选某一方会丢现有条目或独有样本；
  Git 干净也不能证明忽略证据可以删除。
- 证据状态：verified（限本次 Git 双向差异、原件校验与检索测试）；来源设备结论未重测。
- 排除：“较短分支是逐字节子集”“未跟踪文件为空意味着无忽略证据”，均不成立。
- 正确做法：原始 refs 独立可恢复，保留样本与约束，当前语料重建并通过原阈值后才清理。

| 样本 | 内容 | 预期 | 原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 两分支修改同篇知识且各带旧生成清单 | apply | 要做双向差集而非覆盖 | observed |
| 路由反例 | 源分支已完整合入且无任何独有或忽略材料 | skip | 不需要重新做知识整合 | constructed |
| 执行合格例 | 验证 bundle 可独立恢复、保留旧语料及全部样本，按原阈值通过 | pass | 内容与恢复能力都有证据 | observed |
| 执行失败例 | 直接采用旧分支的 381/382 篇清单覆盖当前 387 篇 | fail | 会使新增知识脱离索引 | constructed |

复用既有 `lossless-knowledge-dedup`，不另开治理知识条目、不写生产记忆图谱。

## 最终整合与资源核销

验证后的合并提交 `0034cba` 已快进进入 dev，知识与样本在 task/dev 的树内容一致。
该提交保留扩展版 `64cc515` 的合并祖先关系；窄版独有内容人工无损并入，
其原提交 `933461c` 保存在独立 bundle，而不是伪造 Git 已合并关系。

删除前三个源 HEAD 再次与冻结值核对一致、普通 Git 状态均干净；cwd 与忽略目录打开
文件检查均无匹配。三个 `git worktree remove` 成功；扩展版用 `branch -d`，
失败验收和已整合窄版按本次原生批准，在独立恢复验证后对精确分支执行 `branch -D`。
所有原始提交仍能通过归档恢复，没有删除 bundle、原失败证据或本轮验证材料。

本任务隔离检索状态另保存在 `integration-verification/`，源/副本 checksum dry-run
比较零差异；连同原始材料和独立恢复裸仓，归档约 2.5 GB、根权限 0700。
可用 `git bundle list-heads` 找回原 refs，再从 bundle 的指定原分支恢复 worktree；
复制对应 `*-local/` 恢复忽略材料。历史绝对路径只是证据，不复用旧审批权限。

在本节写入时，Git 中只剩 main、dev 和当前 `task/legacy-branch-closure`。
此文档收尾提交通过 diff 检查并合 dev 后，将结束四个 Skill、调用官方
release-completed-workspace，从 dev 普通 Git 删除本临时 worktree/分支，
再回读 finalize-workspace-cleanup 的 complete。该动作不需要重新运行已通过的知识测试。

main 仍为 `bd216b3`，原有三个 `.ua` 修改和未跟踪 `.sulde/` 保持；未 push、未安装、
未移动仓库或改 remote。原迁移支持任务仍是未实施，不因本次清理而转为完成。
