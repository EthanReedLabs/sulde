# R10 — 私有发布工具与 Claude 安装包边界修复

日期：2026-09-12。结论：本轮范围已完成；R9 的私有 Pro Claude 打包失败已修复。
实现提交 `f21cd5eda55740049c977f31eb79db29324b6df0`，分支 `task/public-harness-export`。
当前会话原生 Allow 应用 revision 8，receipt `16ea60ca…`。没有正式安装、合并或推送。

## 根因与修复

`stage_claude()` 原先按 `scripts/` 前缀收集所有已跟踪脚本，包含新加入的私有
`export_public_harness.py`。它的脱敏转换匹配样本含开发目录，现有包路径扫描因此
正确报错。这不是运行时执行慢、缺少 Python 依赖或 Codex 版本不匹配。
只删匹配样本会损害导出器；只屏蔽扫描则会掩盖发行包内容边界问题。

代码消费者检索仅命中配套 `verify_public_harness_candidate.py`、导出器本身与测试，
没有 Hook、Skill、MCP 或 KB runtime 对这组工具的调用。修复在打包选择层排除
导出器、配套验收器与 `public_harness_overlay/` 的四份素材，共六个已跟踪文件。
源文件全部保留；没有排除整个 `scripts/release/`。打包器、候选安装器、事务安装器
及其他既有运行时/维护工具仍然打包；原开发路径扫描断言不变。

新增正反例覆盖精确文件名、目录边界和相似名称保留；实际 Claude 包测试增加
排除项与维护工具保留断言。没有改 Guardian 授权、Hook、scheduler 或生产接线。

## 验收与复用

| 范围 | 结果 |
| --- | --- |
| 私有任务树 r10-unit-001 | 导出器 29 项及打包 15 项，共 44 项通过，零跳过，23.273 秒 |
| 隔离保护 | 正式 KB 写入违规 0；本机 CLI 摘要未变；没有付费模型调用 |
| 公开候选 validation-013 | 39 项测试、18 组检查全部通过；分组耗时合计 9.131 秒 |
| 宿主包 | Claude、Codex POSIX、Codex Windows 均构包通过，两项官方 Codex 插件校验通过 |
| 独立回读 | 清单、全部文件摘要/执行权限、检查日志摘要、源文件保留和排除集合均匹配 |

原 Windows 原生 PowerShell 专用测试未在 macOS 重跑，仍交 Windows；没有把未执行
标为通过。两轮测试属于不同输入，不合并宣称为一轮全量结果。

公开 `review-013` 仍为 628 文件，较 R9 626 文件不变、2 文件变化（打包器、测试），
零增删。15 条隐私扫描命中及所在行内容均与原审阅集合相同；不新增正式知识语料、
项目记忆、生产账本或私有报告。导出器的 review_only / release_ready=false 保留。

与 R9 的实际公开包逐文件比较：Claude 433 文件仅打包器自身变化；两平台 Codex 包
各 288 文件的字节和执行权限完全一致，包含 generation 描述。因此保留 R9 的真实
CLI/PreTool 双身份验收作为相同包内容的证据，不重新执行安装或编造新 receipt。
这不是 R10 新安装证明；人工审批界面、真实调度、升级回滚与 Windows 原生执行仍未验收。

## 私有证据

清单：`f5c23776dff872ab4af6a396e0f68cff4bf412511774cfb34a38581249618d95`。
以下路径均在任务私有 `.sulde/public-export/`，不进入公开输出：

| 文件 | SHA-256 |
| --- | --- |
| r10-unit-001/results.json | 4b7519e55f138f8b4953dc3a8435c36f96e535ee488349ee74889d2e3a4c0895 |
| r10-unit-001/tests.log | 935c1fb5a383acff950a326e9385fea2b9d3cfbc20f4728681cc3d701a9ce59f |
| validation-013/results.json | 79242c8896cee7f9f1c1912be4c4723a75a5a9e7d9c14f3ac5f589ca7a53a213 |
| r10-independent-readback.json | 1fdd4dace38e3e4c6b13f45f4776fc0063ed99608ced3e52cd766919200f5d66 |

独立检查脚本：[verify-r10-evidence.py](verify-r10-evidence.py)。测试运行时的改动随后
提交为上述实现提交；检查器回读实现及相关源文件与提交内容一致。R9 的原始失败
记录保留，不将其原地改成成功。

## 保留状态与执行复盘

- Pro main=`bd216b3…`、dev=`e61683c…` 不变；main 原三项 `.ua` 修改保留。
- 公开本地 HEAD/origin/main=`9cefc8a…`，工作区 clean；本轮没有网络写入。
- 没有生产安装、cachebuster、marketplace 修改或正式知识库/记忆写入。
- 合同回读 revision 8 active，pending proposal、open event、pending verification 和
  integrity breach 均为 0；本次没有效果成功伪造或授权转移。
- Agent 首次导出误传短提交 ID，被导出器拒绝；读取完整 40 位 ID 后执行成功。
  没有放宽 immutable revision 门禁。原生确认未传 prefix_rule，宿主仍报告保存精确
  前缀；原因继续为 inconclusive，不作为未来 Guardian 授权，不在本轮改宿主配置。
- Intent Guardian 限定本轮修复范围；知识库的失败触发诊断/范围冻结规则使未变化的
  Codex 包复用既有证据；plugin-creator 用于官方结构校验，没有进入重装流程。

## 沉淀候选

证据 verified：运行包按宽目录前缀收集时，新建的源侧发布工具会隐式进入安装包，
使其私有匹配样本触发路径扫描。修复应在制品内容选择层区分发布工具与运行时，
同时排除依赖它的辅助工具和素材，而非改写匹配规则或降低扫描力度。

- 路由正例：新导出器加入 scripts 后，既有 Claude 制品路径扫描首次在本轮证据中失败。
- 路由反例：已安装 Hook/维护流程确实依赖该文件时，不能只因含有开发路径就排除它。
- 执行合格例：确认消费者，六文件精确排除、邻近名称保留，真实包扫描和导出回归通过。
- 执行失败例：整体排除 release 目录、破坏私有导出器匹配规则，或把公开包通过当作 Pro 包通过。

本轮停止线已达到。正式安装与公开增量同步仍需分别选择范围，不自动扩大到两者；
生产业务中的历史 Hook 报错不属于本次修复证明。
