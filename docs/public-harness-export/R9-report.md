# R9 — Codex 0.154.0 兼容性与公开候选隔离验收

日期：2026-09-12。结论：本轮冻结的公开候选兼容性与隔离链通过；不是生产安装完成，
也不是 Pro 全量发布验收通过。实现提交 `4c46f88120880c0312a8eb559fe19faec93139fd`。

## 范围与实现

本会话原生 Allow 已应用为 revision 7，receipt `f4aa9d8f…`；延续同一任务分支。
范围限定为兼容性必要修改、定向回归及隔离候选，不安装生产、不合并、不推送。

- 共享 CLI 契约精确更新为 `codex-cli 0.154.0`。没有改成版本范围，也没有升级或
  降级用户 CLI；旧版本、未来版本、包装/畸形输出仍有拒绝反例。
- 从完整 CLI smoke 提取只读版本预检，prepare 在 Python 环境准备、源码扫描和
  候选目录写入前校验版本及执行器身份；verify 在隔离环境与 registry 写入前拒绝
  旧候选版本和准备后执行器漂移。完整 help、严格权限配置、握手与真实 Hook 验证
  仍然保留，不以便宜的前置检查代替它们。
- 更新相应安装、运行器、打包和候选测试，以及公开 README；保留旧报告为历史事实。
- 本次候选明确绑定已安装的原生二进制，SHA-256 为
  `4f85982624b3898c8991cb80c0981b2aa71070e3537046c9a95950318a95afcc`。
  首次 host-001 只绑定 npm 启动脚本；host-002 和实际候选改用原生二进制回读，未改
  用户 PATH 或 CLI 文件。不能把启动脚本摘要等同于其后台原生二进制摘要。

## 验收事实

| 范围 | 结果 |
| --- | --- |
| 私有任务树定向回归 r9-unit-001 | 104 项：101 通过、2 失败、1 Windows 跳过，350.508 秒；原始失败记录保留 |
| 版本断言修正后 r9-unit-003 | 1 项通过，0.372 秒，零跳过；r9-unit-002 的中间失败也保留 |
| 原生二进制 host-002 | 2 项通过，3.512 秒；真实身份封装/独立运行器回读、严格权限配置与握手、PTY/非 PTY 一致性 |
| 空数据公开候选 validation-012 | 40 项测试、19 组检查全部通过；三份宿主包与两项官方插件校验通过 |
| 官方候选 prepare / verify | exit 0 / 0；1.148 / 17.741 秒，合计 18.889 秒 |
| 独立最终回读 | 628 文件、清单、候选 state/receipt 摘要、真实 denial 事件及双身份匹配通过 |

私有任务树第二项失败为 Claude 包路径扫描命中 `scripts/release/export_public_harness.py`。
该私有导出器不属于公开输出；同一 `test_stages_self_contained_claude_artifact` 在实际
公开候选上通过，扫描规则未删除或豁免。**私有 Pro 打包这一项仍未修复**，不能把
公开候选通过改写为私有源树整组通过。Windows 专用跳过按既定分工交 Windows。
本轮未重跑历史全量，也不将不同运行、不同输入的测试数量加成一轮“全量通过”。

官方资料用于核对接口仍有文档依据：
[严格配置与 CLI 参数](https://learn.chatgpt.com/docs/developer-commands?surface=cli)、
[Hook 与权限配置](https://learn.chatgpt.com/docs/config-file/config-reference)。
是否兼容当前二进制以本轮真实测试为准，不由文档或版本字符串单独证明。

## 真实 Hook 链（不是直接调用适配器或手工灌入 proof）

实际链路：新候选进程 → Codex app-server → 回环模拟模型服务 → unified exec → 候选
Hook → 独立 finalize。付费/外部模型请求为 0，生产 KB 写入违规为 0。

- 合同内与计划路径外的普通本地写入均成功，符合已收窄的 Guardian 边界；这里不再
  用普通越计划路径写入作为应拒绝的负例。
- 删除负例为 `candidate_native_2`。prepare 先建立唯一 `/private/tmp` 测试标记；
  真实 `rm -- <marker>` 被 PreToolUse 拒绝，finalize 确认标记仍存在且内容为 probe ID，
  随后清理该专用标记。**标记不是“从未产生”；最终不存在是清理后的状态**。
- 独立回读的 started event `e3c81a9d5d04d6181b451546` 与本机宿主 session、call ID、
  `loaded_module_generation` 和 `artifact_generation` 均匹配，supervision 为 live_verified。
- proof：`63d055669c4c533cf12e817d7f6268c956632ad63793346708f60327e0bc2d1a`。
- receipt：`6dbc30a8e0075a2f2cd95b38cb969a4000336a26ec03c0e552656347e2ba2b35`。
- runtime tree：`cd25164488618a637aeae81f812105338827ba501d82569eb4630e7a35f11808`。

候选 registry/cache、launcher 和 MCP 入口在隔离根内得到验证。scheduler 仅验证
16 个标签的入口 dry-run，`scheduler_host=unobserved`；`native_permission_ui=unobserved`。
本会话批准 R9 的真实 Allow 属于现有正式插件，不能充作候选插件的人工界面验收。
完整事务安装、升级回滚和 Windows 原生执行均未执行。

## 公开快照与证据

候选 `review-012/tree` 仍为 628 文件：相比已发布 R7，620 文件不变、8 文件修改、
零增删。清单 `81efdc6b796940d116fe628af2d2c28368ef12b35696dd64514495b95a5d483c`。
原 15 条扫描命中位置与所在行内容一致，没有新增私有语料、记忆、生产账本或内部报告。
公开候选的 Git 历史是独立合成历史，不含 Pro Git 对象。

以下证据在任务私有 `.sulde/public-export/` 保留，不公开同步：

| 相对路径 | 文件 SHA-256 |
| --- | --- |
| r9-unit-001/results.json | 0b0fc34eb0ceb8394fc72184814b34e545c617912cc28900ed0167cc2d035af7 |
| r9-unit-003/results.json | a0f5bc104e80bd1ae71f217c5398cb35f9813a932040b4ebf82636194e0a140f |
| r9-host-002/results.json | 15772aa832e47dba4dd720f5cdc8a87bf6e220021e93b3bfacf560450eb6e18a |
| validation-012/results.json | 647bcf4390eb86cf0c38ad5415e94aaa7215414c8631d024df2d9343c7e88f51 |
| r9-candidate-001/summary.json | 99901337105aa4bf44731198987174b954150f319a406a90a1b622dcee35b016 |
| r9-independent-readback.json | e1bad1466eb5794195b8eadb37a392b71acb0747194a298c153f858f09746c6e |

## 保留边界与执行复盘

- Pro main=`bd216b3d29e37b1aaf0e6be0c930b5221a925562`、
  dev=`e61683c08aaf97db3e8e9d105ea3154ec217061c` 不变，main 原三项 `.ua` 修改保留。
- 公开本地 HEAD/origin/main 仍为 `9cefc8a3875dafa49de9d95db68e69a74bc56da5` 且 clean；
  本轮无远端写入。没有 cachebuster、生产安装或 promotion，当前候选也不应直接
  当作生产升级件复用版本号；生产发布仍需独立冻结与正式维护授权。
- 原生确认调用未传 prefix_rule，宿主再次报告保存了精确前缀；未将它当作后续
  Guardian 授权，原因仍 inconclusive。本轮没有修改宿主配置解决它。
- Agent 自身问题已记录：版本扫描测试有两处分支断言遗漏更新；独立回读器最初错误
  假设负例目标在候选目录内。实际设计是在系统临时目录建立专用删除标记，核对
  prepare/finalize 原文后纠正为精确 probe ID/目标/命令核验，并再次回读通过。
- 任务续接与 Intent Guardian 保持 revision 7 范围；知识检索的冻结规则使已通过的
  安装器证据得以复用；OpenAI Docs 与 plugin-creator 用于接口依据与官方包校验。
  没有写正式知识库或项目记忆。

## 沉淀候选

证据 verified：已知精确版本不匹配可在候选目录、环境与构包前拒绝；首轮已通过的
模块可按输入摘要复用，不因一个版本断言返修重跑全部安装故障注入。真实新版本
兼容性证据必须来自原生二进制和实际 Hook 链，而不是只改版本常量。

- 路由正例：版本升级后重复进入候选重操作，最终才被精确版本门禁拒绝。
- 路由反例：help/权限/Hook 真实行为未知，不能因为版本匹配就跳过这些检查。
- 执行合格例：先做精确廉价拒绝，再保留完整实际宿主链；分别记录人工界面/调度
  未观测域，并明确删除负例的“预建→拒删→验证→清理”语义。
- 执行失败例：改成任意版本、伪造 CLI、把模拟调度或标记清理后的不存在当作未执行
  的唯一证据，或把公开候选验收等同于私有 Pro 打包全部通过。

下一阶段选择应在正式安装、公开增量同步、Pro 私有打包修复中明确其一，不能因本轮
隔离验证通过而自动执行三者。当前停止线已达成，未验证域仍保留。
