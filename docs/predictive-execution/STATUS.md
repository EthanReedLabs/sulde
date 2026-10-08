# predictive-execution 任务状态

- 分支:`task/predictive-execution`(自 dev `d7b04bc` 创建,含编排 A R3 closeout 合并)。
- worktree:`.worktrees/predictive-execution`。
- 任务文档:`docs/predictive-execution/`;原始证据:`/Volumes/Optimus/Sulde/tasks/predictive-execution/`。
- 方案来源:已合入的 `docs/sulde-orchestration-iteration/PREDICTIVE-EXECUTION-PLAN.md`
  (frontmatter task_id `sulde-predictive-execution`, tier deep)。不在本任务内改写该方案;
  语义以已合入版本为准,避免双真值。

## 阶段

| 阶段 | 状态 | 产出 |
| --- | --- | --- |
| 启动 | 完成 | 分支/worktree/证据目录就位;方案已读 |
| B0 能力矩阵+预算冻结 | 完成(d67f91e) | B0.md |
| B1 影响预测 | 协议实现完成,待接线 | scripts/kb/impact_prediction.py + 12 测试 |
| B2 增量判断 | 完成(R1-03 补少改事实) | incremental_facts + execution_judgment |
| B3 纠偏生命周期 | 完成(R1-02 回放同不变量+证据绑定) | 49 测试 |
| R1 修复轮 | 完成(f8191af…11e2530) | R1-REPORT.md;受管链已接线 |
| R2 修复轮 | 完成(R2-01…R2-04) | R2-REPORT.md;真实 Agent 两轮行为证据;基线/身份/重绑修复 |
| R3 真实入口轮 | 行为验收通过;流程验收未闭环(R3 报告披露) | R3-REPORT.md |
| B5 经验反馈 | 完成:召回经正式入口改变验证动作(R1-05) | |

## 范围边界(启动时登记)

- A(编排迭代)代码已合入 dev `d7b04bc`(merge `d7b04bc`,回归 22/22 通过);
  **A 的生产安装验收未做**——按协调端 2026-09-27 指示"不重复安装或全量测试",
  该缺口登记为独立待办,不作为本任务已完成项,也不由 B0-B5 默默补齐。
- command-effect 修复(另一任务)的通过不代表本任务能力已验收;两者证据分开引用。
- B 不新建审批控制面、不管理 Git、不做每工具调用模型审查、不采集隐藏推理、
  不产生效果债务或跨 session 阻塞。生产安装/外部模型成本/范围扩张需对应授权。
- 本任务不自行 accepted;阶段产出交协调者独立复核。

## Dogfood 记录(真实宿主行为证据,2026-09-27)

- B5 动手前开真实预测 `pred-fc7ba0c164f698986c9f3103`(预测文件:
  `~/.sulde/data/predictions/predictive-execution.jsonl`;判断账本:
  `~/.sulde/data/predictions/judgments.jsonl`)。
- 实现 agent-experience TTL + prediction `based_on_experience` 期间,对照探针
  暴露一个真实潜在缺陷:verified 经验的年龄解析不认 `Z` 后缀,解析失败会
  静默保留权威——已在同一提交内保守修复(无法判定年龄 = 过期,不驱动策略)。
- 对照结论:`as_predicted`(触及面与预测一致),发现时点 = 实现完成前,
  非事后报告。监督端独立回读前,预测保持 open,不自行 verified。

## R1 轮(2026-09-27)

- 五项(R1-01…R1-05)逐项提交 f8191af / 6ebe23d / bdb8df6 / d28d9ac+fd90df2 /
  11e2530(含 9779485 范围撤回)。B 套件 97/97。
- 证据:`/Volumes/Optimus/Sulde/tasks/predictive-execution/R1/`;
  报告:`docs/predictive-execution/R1-REPORT.md`。
- 状态:candidate-awaiting-independent-review;未合并、未推送、未安装。

## R2 轮(2026-09-27)

- R2-01 证据隔离与 R1 更正(a8e7ddf);R2-02/03 基线绑定与身份纪律(4dc4c28);
  R2-04 真实 Agent 两轮行为证据(独立探针验证);R2 报告 005c4cb。
- 真实 Agent 样本:缺陷任务(稳定性标准经反馈驱动修正)+ 正常任务(零误报)。
- 证据:`/Volumes/Optimus/Sulde/tasks/predictive-execution/R2/20260927T141800-AB8A21E5/`。
- 状态:candidate-awaiting-independent-review;未合并、未推送、未安装。

## R3 轮(2026-09-27/28)

- R3-01 合同版本规范传递 + 缺失降级(d905a16);R3-02 漂移范围语义
  (65c9033);校验顺序前移(48bb5fc)。
- R3-03 无模型真实入口链:正常路径 checked+独立验证通过;纠偏路径
  larger→排队→正式续接(--retry --retry-op)→修复→as_predicted(经实际
  agent-runtime run,fake provider)。接线缺陷修复:预测事件缺 provider。
- R3-04 真实 Claude 经受管链:行为验收通过(exit 0,average 50);
  报告契约门两次未过 → run failed —— 真实集成发现,如实披露,留待
  provider 命令层结构化解决。预算 ≤2 次任务级调用已用(第 3 次为同标准
  诊断重放)。
- 证据:`/Volumes/Optimus/Sulde/tasks/predictive-execution/R3/`。
- 状态:candidate-awaiting-independent-review;未合并、未推送、未安装。

## R3-followup 轮(2026-09-28)

- 反馈消费链接通:prompt-time 预览校验 + post-spawn confirm(真实 run/session
  入册);执行输入实测含反馈段(fake provider stdin 捕获)。
- 三路径 + 反例测试全过;R3-REPORT 追加 SUPERSEDED 更正(入口链结论与
  R3-04 归因),超时诊断成文(R3-TIMEOUT-DIAGNOSIS.md)。
- 本轮真实模型调用 0 次。状态:candidate-awaiting-independent-review。

## R3-CLOSEOUT 轮(2026-09-28)

- 一:合同/续接身份校验修复——rebind 不再覆盖绑定合同版本,只记录
  attempt_contract_version;跨合同续接 → 反馈失效保留;同合同合法续接正常消费。
  生产顺序回归(实际 run 命令)通过。
- 二:消费时序绑定实际 stdin 送达(on_input_delivered 回调);registry 参与
  load 判定;七场景全过(含降级与零新建文件);未启用预测任务零新建。
- 三:超时诊断精化——permission_denied 配对(3+4 次)揭示报告契约与权限
  轮廓的结构性冲突;"240s 不足"表述撤回;量化贡献 inconclusive;
  下次真实验收最小准备已登记。
- 报告:`docs/predictive-execution/R3-CLOSEOUT-REPORT.md`、
  `R3-TIMEOUT-DIAGNOSIS.md`;证据:
  `/Volumes/Optimus/Sulde/tasks/predictive-execution/R3-closeout/`。
- 状态:candidate-awaiting-independent-review;真实模型调用 0;
  未合并、未推送、未安装。

## R3-INJECTION-CLOSEOUT 轮(2026-09-28)

- 故障注入收尾:四个已知缺陷全部"基线红 → 修复后绿"
  (stdin 失败登记 / 旧确认删新请求 / 来源自我消费 / 无预测任务写账本)。
  消费确认绑定实际 stdin 送达;确认只删一致工件;来源=消费 以持久化摘要拒收;
  无预测任务 skipped 零写入。冻结矩阵九场景全过;受影响套件 133 项全绿。
- 证据:`/Volumes/Optimus/Sulde/tasks/predictive-execution/R3-injection-closeout/`
  (基线红日志 + 复验绿 + 哈希清单)。
- 报告:`docs/predictive-execution/R3-INJECTION-CLOSEOUT-REPORT.md`。
- 状态:candidate-awaiting-independent-review;真实模型调用 0;
  未合并、未推送、未安装。

## R3-followup A 轮：双版本对照（incomplete, 2026-09-28）

- 双版本对照测试已创建但标记 incomplete：两个版本均因同一基础设施问题失败
  （control cannot be read safely: FileNotFoundError — 提取的源码树缺少
  managed chain 所需的 control root/brief 文件）。
- 此为测试夹具缺口，非版本差异（新旧版本同一错误证实）。
- 提交：5c1f9d7（含协调端 VERIFICATION-RECOVERY-TASK 合入）。
- 状态：incomplete — 需要补齐测试夹具的 control root 设置后重跑。

## 2026-09-28 验证恢复 A/B/C（当前有界结果）

- 状态：candidate-awaiting-independent-review；不是 predictive-execution 全能力 accepted。
- A：9f23fa2 修复测试驱动，复用已有 _Chain；双版本各无反馈/反馈续接正常控制通过，
  缺失消费事实工具负控两侧均非零；独立 probe 通过，证据已写 Optimus 并回读验哈希。
- B：原单版本 4/4 不证明双版本；撤除脚本、提交、推送都不等于验收。原 R1/R2
  夹具失败不是有效缺陷基线；R3-INJECTION-CLOSEOUT 的“旧红新绿”不因本次正常控制获追认。
  上节“基础设施阻塞”更正：原测试未创建 brief/初始化预测，已有合法 local_reuse 与夹具；
  两侧前置失败只说明未测到目标路径，不能据此推断新旧实现无差异。
- C：五份既有派单规则按摘要集成，支持授权内连续执行与集中复核；不是新增控制面。
- 入口/反馈/派单 62 项通过；本次生产 scripts/ 零改动，无模型调用、合并、推送或安装。
- 历史债务、EPIPE/B2、真实 Agent、多样本、A 的 C 层及资源清理仍为独立未完成事项。
- 当前报告：VERIFICATION-RECOVERY-REPORT.md；此前记录保留为历史。

## 2026-09-28 B1/B2 有效验证接手（当前：incomplete）

- 原 Dev 在 fd02cce 交还后无新实现；协调执行者接手测试侧，不冒充非作者独立复核。
- B1 已取得同一真实断管反例：fcd28a4 误消费/删除工件，5a2d951 正确保留并登记不确定。
- 候选显式恢复路径通过；未恢复后下一运行收尾覆盖原 request，B2 不变量失败。
  新工件不再命中旧 registry 键，实际 preview 返回 delivered；没有声称再次真实发送。
- 原无效三项测试修成四项：3 通过、B2 1 失败，失败保留，不 skip。
- 正式证据在 Optimus injection-verification/20260928T113000-b1-b2，596 项哈希回读通过。
- 测试/报告提交不等于产品修复。scripts/ 未改，按 tests-only 停止，未合并/推送/安装。
- 后续需要允许精确修复反馈工件覆盖与恢复门控一致性；详见 INJECTION-VERIFICATION-REPORT.md。

## 2026-09-28 B2 有界生产修复（当前结果）

- 用户确认扩展生产修复；d1a7296 仅修改 prediction_feedback.py，保留未恢复 exact request，
  新观察继续入 check 账本，明确披露暂缓覆盖；不自动恢复、不新增控制面。
- 同驱动对比 7fb4c53→d1a7296：B2 旧红新绿；B1/直接恢复保持通过，
  未恢复运行之后再恢复也通过，独立探针 ok 2。
- 定向与受影响回归 41+32=73 项通过；正式双版本归档 654 项 SHA256 回读通过。
- 状态：candidate-awaiting-independent-review。不是全项目 accepted；未合并、推送、安装。
- 报告：B2-PRODUCTION-REPAIR-REPORT.md。前轮失败记录与证据均保留，非作者独立复核未完成。
