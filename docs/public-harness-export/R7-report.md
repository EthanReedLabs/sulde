# Public Harness export — R7 公开同步完成

日期：2026-09-12。结论：经本会话原生 Allow 确认，完整 Harness 代码快照已公开同步，
远端与本地公开 main 均独立回读验证通过。不是正式安装或生产就绪验收。

## 发布结果

- 仓库：`https://github.com/EthanReedLabs/sulde-cc.git`，分支 main。
- 公开提交：`9cefc8a3875dafa49de9d95db68e69a74bc56da5`。
- Git tree：`6add687d53a04083c8790a209ea9fb0c9d4b3805`。
- 父提交：原公开基线 `c966bae1477423ee3a64fd2a6d02fdcb91a43913`。
  只增加一个公开提交；临时发布分支从公开历史建立，没有合入任何 Pro Git 历史。
- 本地公开 checkout 的 HEAD 与 origin/main 相同，工作树干净。
- 清单：628 文件；新增 481、修改 40、保留 107、删除 0。原许可证与作者归属保留。
- 正式知识语料/索引/向量、真实项目和会话记忆、生产账本/回执、内部报告及私有
  Git 对象不在发布树中。正式知识清单仍为零篇，只有空清单/索引及通用沉淀规范。

## 公开前最后一项纠正

逐文件对照原公开仓库时发现，按 `.ai-workspace` 目录名排除会误移除 28 份已有公开
脚手架 README。它们描述目录用途，并非用户填写的任务数据，应保留。

`bf0884f` 将例外限定为四个平台、七个目录的精确 README 路径，且只从冻结公开基线
读取；同名 Pro 文件和真正任务正文仍排除。新增回归覆盖“原公开说明保留、私有同名
覆盖不得进入、实际任务正文仍排除”。29 项导出器测试通过，零跳过，4.530 秒。

最终候选为 `.sulde/public-export/review-011/tree`；源提交
`bf0884fea7495a538af7faa5d7c90c974fba0421`；manifest 为
`bf2953a555195a2731b6edc55ca9b297ee09472e02042879fdb61d186a9fb7d6`。
R6 已审阅的 600 文件逐项摘要、模式和来源记录相同；新增 28 文件与原公开 blob 字节
及模式相同。原 15 条原始扫描命中不变，未修改扫描器或豁免私有目录。

因此复用 R6 的 80 项候选测试和内容审阅，不重复全量历史测试或重新构包；不声称为
628 文件新跑了一轮正式安装验收。

## 授权与独立验证

原生 proposal 确认已应用为 revision 6，receipt 为 `ccd56548…`。公开目标、628 文件
快照、不携带私有数据、不安装、不强推和发布后无法收回副本均已在卡片中展示。
确认结果完整引用见 [R7-publication-result.json](R7-publication-result.json)。

执行证据：

1. 公开前从 GitHub 读取 main，仍是冻结基线。
2. 独立临时 clone 只包含公开历史，在任务分支机械同步冻结文件，不删除原公开文件。
3. Git index/tree 的 628 个 blob 摘要、模式、路径全部等于候选 manifest；提交的
   parent/tree 再次核对一致。
4. 以普通快进 push 更新指定 main；未使用 force 或更新其他远端分支。
5. 从 GitHub fetch 到另一份原公开 checkout，重新读取远端提交的所有 blob/模式，
   628 项全部匹配。确认无脏文件、忽略文件覆盖冲突或符号链接父路径后，本地 main
   仅作快进。
6. 当前合同回读：pending proposal 为空、pending verification/open event/integrity
   breach 均为空。Git 结果由实际提交/远端对象验证，不以控制面回执代替。

原生确认前生成的 [R7-publication-plan.json](R7-publication-plan.json) 作为计划时点
记录保留；其 awaiting/未授权字段不覆盖本报告中的后续 applied/published 事实。

## 保留边界与独立问题

- Pro main=`bd216b3d29e37b1aaf0e6be0c930b5221a925562`、
  dev=`e61683c08aaf97db3e8e9d105ea3154ec217061c` 不变。
- main 三项既有 `.ua` 用户修改保留；没有修改正式安装、正式知识或项目记忆。
- Pro 任务分支未合入 dev，保留本地任务 worktree。临时发布 clone 保留在忽略的
  `.sulde/public-export/publication-001` 作为证据，不是挂靠 Pro Git common-dir 的 worktree。
- R3 全量历史失败/跳过及尚未完成的安装、live Hook、调度、升级回滚、Windows 原生
  验收继续保留；公开同步完成不代表它们已通过。
- R6 的只读 bootstrap 组合调用被拒绝仍为独立未归因问题，未借本轮绕过执行。
- 本轮未传 `prefix_rule`，但宿主报告保存了原生批准命令的精确前缀。只依据匹配的
  native applied receipt 接受权限，没有将该前缀当作未来授权；原因 inconclusive，
  未改宿主配置。一次沙盒 DNS 失败通过正常原生联网权限重试解决。

任务续接与 Intent Guardian 用于展示和落实这次公开范围确认；知识检索的范围冻结
规则避免重新展开私有历史测试。未进行额外知识/记忆入库。

## 沉淀候选

证据 verified：隐私过滤必须区分“真实任务目录”与“原公开的空脚手架说明”。单看
`.ai-workspace` 名称会误删除公开功能资产。

- 路由正例：公开同步 diff 将原公开模板 README 列为删除。
- 路由反例：该目录内用户填入的正文、运行日志，或 Pro 的同名私有覆盖。
- 执行合格例：精确限定公开来源与路径，原公开 blob 等值保留，正反例验证后再发布。
- 执行失败例：豁免所有 `.ai-workspace`、复制私有模板覆盖，或只看候选内部 diff
  而不对照实际公开目标的新增/修改/删除清单。
