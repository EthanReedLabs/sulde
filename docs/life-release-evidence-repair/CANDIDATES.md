# 沉淀候选：验证边界与成功证据

## 任务与意图

- 问题类型：bug-fix / host-inconsistency / intent-drift。
- 任务目标：修复候选隔离、生命体问题关闭、真实宿主验收及 Hook 版本归因。
- 用户真实预期：控制面继续收窄；Agent 执行普通任务，保留高风险人工权力；测试应覆盖真实执行边界并避免无效重跑。
- 触发场景：多会话环境变量、观测数据库不可读、候选 Hook 尚未受信、Hook 执行期间文件换版。

## 观测与证据

- 可观察症状：候选继承父合同；观测 unavailable 却关闭问题；未受信 Hook 不执行而协议测试返回 deny；执行 A 却记录文件 B 摘要。
- 期望与实际差异：可用性、执行及身份事实不能由准备状态、空结果或执行后的路径内容替代。
- 已确认根因：环境使用全量父进程副本；关闭逻辑丢弃 aggregate 状态；候选原验证直接注入 Hook 事件；观测器在子程序结束后计算身份。
- 已排除假设：普通计划外本地写入被放行不是本次缺陷。最新 policy 明确将任务路径降为规划数据；重加路径授权会违背用户既有决策。
- 证据状态：verified（构造回归及隔离真实 CLI 证据，不冒充历史生产事故）。
- 一手证据：本任务 test-evidence 红绿记录、真实 CLI PreTool/PostTool 日志和源码 diff；具体索引见 REPORT.md。
- 正确做法及验证：入口自身白名单隔离；观测不完整保留 inconclusive；真实 CLI 请求统一执行器并回读实际 Hook 拒绝与 v2 proof；同进程加载字节绑定摘要，外部子进程发生路径漂移则身份 unknown。

## 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 候选 verified 但 native Hooks 未受信 | apply | 协议结果无法证明宿主执行了 Hook | observed（隔离 CLI） |
| 路由反例 | 普通写入超出规划 allowed_paths 但仍执行 | skip | 当前策略明确不把普通路径作为授权门，不能按旧策略修复 | observed（源码及隔离 CLI） |
| 执行合格例 | 本地正常动作执行、未授权删除被真实 PreTool 拒绝，独立 finalize 核验同 session 和双代际 | pass | 同时证明成功路径可用及所保留的高风险边界有效 | observed（隔离 CLI） |
| 执行失败例 | 直接调用 Hook 得到 deny 且 marker 未产生 | fail | 没有真正提交动作给宿主，marker 缺失不能证明预拦截 | observed（旧实现） |
| 路由正例 | 验证期间观测库损坏而 last_event 未更新 | apply | 无法观测复发不等于没有复发 | constructed（真实 SQLite 损坏） |
| 路由反例 | 数据库可读且没有新事件 | skip | 正常的零增量不应被一概当作故障 | constructed（正常关闭回归） |
| 执行合格例 | verifier 退出 0、观测不可用，保存测试结果但问题仍 open/inconclusive | pass | 分离测试结果与问题关闭证据 | constructed（红绿回归） |
| 执行失败例 | 观测 unavailable 或 saturated 仍 closed/verified | fail | 把证据缺口升级为验证成功 | constructed（修复前反例） |
| 路由正例 | 运行中的脚本被替换，结束后归因到新文件 | apply | 路径当前内容不是已加载内容 | constructed（真实自改写子进程） |
| 路由反例 | 外部模块只有稳定路径快照、没有加载字节回执 | skip | 只能报告 stable_path_snapshot，不能宣称同进程 loaded_bytes 证明 | constructed（接口边界） |
| 执行合格例 | 同进程编译 A 的字节并记录 A；外部子进程换版时模块身份 unknown | pass | 不伪造无法证明的加载身份 | constructed（红绿回归） |
| 执行失败例 | 执行 A 后读取路径 B 并写入 loaded_module_generation | fail | 审计身份跨执行边界漂移 | constructed（修复前反例） |

## 上浮边界

- 必须泛化：用户、项目、机器路径、session、提交与 artifact 标识；不得携带任何权限 token。
- 可复用内核：不将准备状态、空观测和路径快照替代真实执行证据；审查前先回读当前授权策略。
- 建议容器：anti-patterns，先与 0224 验收环境失真判重，避免重复条目。
- 候选消费者：候选发布器、故障关闭器、Hook 观测器、代码审查清单。
- 只保存在任务分支；本任务不直接写共享 KB 或记忆事实层。
