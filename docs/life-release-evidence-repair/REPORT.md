# LIFE release evidence repair — 2026-09-08

## 结论与边界

四项源码修复和受影响测试已完成；官方候选 prepare/verify 已在干净提交上通过。
本报告不是生产安装或跨平台最终验收，不宣称业务历史故障已经归因或消失。

基线：dev a0ba44b02370b07dcd12f0892686afe84ec4160a。
任务：task/life-release-evidence-repair。未合并、推送或安装生产。
main、dev、其他 worktree、原有 .ua 修改和生产配置不在写入范围。

## 四项修复

| 问题 | 修复 | 验证 |
|---|---|---|
| 候选全量继承父进程环境 | 候选入口自行白名单隔离；HOME、XDG、临时目录及宿主/数据目录由候选拥有；不继承旧合同、session、凭据、PYTHONPATH 或代理 | 父环境敏感 sentinel、隔离路径回归及真实候选测试 |
| 观测不可用仍关闭 LIFE 问题 | verifier 前后都检查 observer_status；非 observed 保存 inconclusive，不把退出 0 等同问题已关闭 | unavailable/unobserved/saturated 和验证中实际 SQLite 损坏反例 |
| 候选协议注入冒充真实宿主链 | 实际 Codex app-server 新进程发现/信任候选六个 Hook，实际 exec_command 统一执行器执行正负例；v2 独立 finalize 匹配 session、真实事件和双代际 | 原生 Hook blocked 通知、真实 started event、同代际 proof；安装器拒绝旧协议-only receipt |
| 结束后文件摘要冒充已加载身份 | 同进程按实际 compile 字节记录；外部进程前后快照漂移则 unknown；artifact 换版独立标记 | 脚本执行期间真实自改写、artifact 替换、PostTool runtime 替换 |

重要审查纠偏：当前 policy.py::_paths_allowed 有意将普通本地任务路径降为规划信息，
不是权限门。计划外普通 touch 放行是正确行为，本次没有恢复普通路径拦截。
真实正例同时覆盖计划内和计划外普通写入；负例使用既有 v2 未授权 destructive canary。

原生 fixture 使用回环 Responses 服务，不连接付费模型、不加载生产凭据。
模型返回只是固定工具请求；执行、Hook 事件、审计和 proof 均来自实际 CLI。
接口参考：[Codex app-server](https://learn.chatgpt.com/docs/app-server)，
实际调用以本机 codex-cli 0.153.4 的接口及真实运行结果为准。

## 测试证据与复用

原始运行记录位于仓库 .sulde/data/test-evidence，JSON 绑定命令、解释器、
runner/source 摘要、结果、时间和日志 SHA-256；失败记录不作为成功缓存。
当前记录 TTL 为 30 天。正文/指标及 native-posttool.json 随任务报告保存。

| run_id | 结果 | 说明 |
|---|---|---|
| 20260908T022211.416040-c1bbc8f20dd9 | 环境失败 | 双层 macOS sandbox-exec 不允许；随后通过宿主原生批准在外层启动仓库 OS 隔离器，并未取消生产写禁止 |
| 20260908T022907.222872-c1bbc8f20dd9 | 红：4 项，6 条断言失败 | 修复前四个根因的最小回归 |
| 20260908T023026.486264-dc8b94fd9cb8 | 绿：4 项通过 | 最小修复回归 |
| 20260908T024657.690723-353230ff7a9a | 真实原生 PreTool 通过 | 候选 artifact、实际 CLI、统一执行器及 v2 proof |
| 20260908T024929.186248-21a8de44966d | 134 项：133 通过，1 个新增夹具错误 | 347.214 秒；真实 PreTool/PostTool 均通过；夹具缺少 PostTool payload 导致 business_effect 断言 KeyError |
| 20260908T025659.043243-394d7e52178c | 15/15 通过 | 只修补该夹具并重跑整个观测器模块，3.048 秒；产品源码未再改动 |

最终受影响 134 个测试的有效结果由组合运行与夹具修正后的模块复验共同覆盖。
不能将原始 134 项运行改写成全绿；也没有因只改夹具和报告重复运行已通过的安装器套件。
这不是全仓全量测试；旧全量结果仅作为未变代码的基线。

组合运行 workspace_sha256：
10735dc4c57ec98245ba91d85256d0d1ddeaec60f49f0681ca42e547819b201b。
夹具修正后最终源码/测试 workspace_sha256：
127f996171947718a82650f0278edd711f10527eb0f9f4cebdd9ba95f18555d2。

关键日志 SHA-256：

- 红：f4a8948534d69bc7bf0ff8285533890cbbecfc2bdcdf2cac525f105192b41264
- 最小绿：5d85f5a4188818c692d0dcce19b578e97e91d632e115ac2d4b8b953a57b0ead8
- 组合：c0e903f8885c4bba75dfed2d85c7a8d5fcca9823b5add0b215992594dd08de6b
- 最终模块：5125360b6a44bd6bcccfac7a476e7eb1a984f33632c15d260858e465f032edb0

## 真实宿主证据

组合运行原生 PreTool：

- session：01a07ef0-e31b-7602-b976-62f1ee1236f0
- call：candidate_native_2；started event：e4b183ead9fe6dbd0ec60e22
- proof：26e630b695434e25a7b0a468423c206ae6baecd32740b40302c3f278dfe255bd
- loaded_module_generation：24758f0ed469d1a52f74d12983f7cb75d11e778ef0cce7ec816707b7c08c7d5d
- artifact_generation：0.2.5+codex.20260907071718-6e84c50faf:43df54af2ac09970a400b15a27b369cfd2f6a47734873470e5ac2ccd0d79ed52
- 两次普通写入成功；一次未授权删除被宿主 PreTool 拒绝；独立 finalize 校验 marker 未被删除后才清理 marker。

PostTool 证据见 native-posttool.json：4 次真实工具执行，project/sulde/third_party
三类来源、12 条故障事实（另有 4 条交付事实），新会话、续用、worktree 切换均覆盖。
无直接 ingest；此 fixture 未安装 Guardian，不冒充生产完整 Guardian 链。

## 性能与未关闭项

官方候选验收见 candidate-verification-summary.json：

- 精确修复提交：8711c79fba3af47c69b462bc107c9aabc9eaaef1，运行前工作树 clean。
- prepare 1.728 秒、verify 18.350 秒，合计 20.078 秒；两阶段 exit 0。
- OS 隔离器的 production_write_attempts=[]，未 promotion，未正式安装。
- 新 session 原生 proof：73f11b4b73cf3931d8c0ce8e2e41ffd6893648a430a1ca3a8e657d62805a9ebf。
- started event：ed00c7ea465f535c731e1de6；call=candidate_native_2；双代际与上文一致。
- 密封 receipt：61fd8c73f013f3b35cb3fa9350a10fc0a5cbb4c0e5e7a63c34985de87999d2c3。
- Hooks 的早期 discovery 是 review_required；原生 fixture 只信任隔离候选的精确六项摘要，
  完成后恢复候选配置。这不是生产信任批准。native_permission_ui、scheduler_host 仍 unobserved。
- doctor 命令 exit 0，但其语义投影仍 degraded（候选未注册 production owner/当前交互 lane），
  不将这条命令测试结果升级为全局 operational ready。
- 后续只追加本报告和候选摘要，产品源未改变；无需再跑完整测试或重新制作同内容候选。

latency.json 保存完整原始样本及源码摘要，复用 R1 的独立测量脚本：

- 普通 wrapper：35.569 ms 中位数；无 observer 基线 20.535 ms，增量 15.034 ms。
- bridge 普通 wrapper：44.962 ms；无 observer 基线 33.760 ms，增量 11.202 ms。
- 直接 wrapper 严格 15 ms 预算本轮略超 0.034 ms，不能报告性能全绿。
- 测量为相同解释器、独立新进程、临时数据、无业务效果；bridge 不含 Guardian pre-dispatch，
  不代表完整生产调用耗时。未为追求通过而重复测量或放宽门槛。

Windows 原生验证、Desktop、未包装第三方 Hook、observer 启动前故障、生产升级后
真实业务观察仍不在本轮完成声明中。候选 scheduler 是隔离/dry-run，不是正式 launchd 安装。

调试期间保留失败事实：未信任 Hook、CLI schema 差异、旧普通路径假设造成的失败。
早期失败在 finalize 前停止，可能保留本任务 canary 临时标记；不按模糊通配删除共享 /private/tmp。
成功运行均由独立 finalize 核验并清理自己的标记，不宣称所有历史测试资源已清理。

## 技能与沉淀

intent-guardian 冻结四项范围并通过原生 Allow；
kb-search 的 0224 验收环境失真规则推动真实 CLI 验收；
plugin-creator 校验插件结构，本轮不更新 cachebuster 或生产 marketplace；
dispatch-task 保留用户要求的 task-only/no-switch；
openai-docs 用于本机原生 CLI 接口核对。

CANDIDATES.md 保存结构化、已脱敏的单写者沉淀候选；未写共享知识库或记忆事实层。
