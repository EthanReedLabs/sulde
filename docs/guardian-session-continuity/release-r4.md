# r3/r4 集成与本地发布结果

状态：**已合入 dev 并安装；当前会话真实 Hook 通过，但历史多跳会话的完整交互验收未闭合。**
不将安装成功、doctor 的退出码 0 或零 effect debt 等同于整体 ready。

## 本轮完成

- r3：Community 既有导出项摘要、四个测试文件七处显式 UTF-8 解码门禁已修复；没有导出 Community 或修改模型策略。
- 单条遗留 apply_patch 已由上一轮真实 Stop 追加结算为 inconclusive；原 started 和原事件摘要保留，没有虚构 completed 或成功效果。新增多文件正反例验证不同 session、重复 Stop 和后续提案边界。
- 开发提交 `44e8ca7e0135a23e95f583a54f874b4e90f507b5`，其 exact HEAD 完整隔离测试 2,001 项：1,976 通过、25 跳过、0 失败，708.588 秒；证据包装器 710.311 秒。测试前后内容身份均为 `b817a254ec4b6e1893da796ca34024c62d04d4b115a44b9604bfe3c1e8f37378`。
- 25 项跳过：17 个已退役 Git 策略、5 个 Windows 特定用例、1 个外层 Seatbelt 限制、2 个必须显式给 baseline 的性能用例。两项性能已在独立同机比较中通过固定阈值，并非以跳过代替性能验收。此前失败证据继续保留。
- 版本字段提交 `13c1b2ed7c0c3f7ea47de8f5541fba49abd92f87`，与 dev 相同；相对开发提交仅 manifest version 改变。未重新运行全量，而是运行精确发布件的隔离候选验证。
- r4 原生 Allow receipt `b39b8973ad6b5da873bf58278305e809497d359c0194863d6c90a4839cecc60b`。两个密封 grant 各消费一次、分别由 cachebuster/install 独立 verifier 结算为 system_verified。无 open event、pending verification、effect debt 或 pre-execution gap。

## 发布与真实生产证据

- 本地版本：`0.2.5+codex.20260908105202-14c038deda`。
- generation：`0.2.5+codex.20260908105202-14c038deda:845668a25b42f608a2a54efb0f603dce419862a9d631dd58104c2369725961c7`。
- loaded module generation：`6092aeb36ec1863e162590620aa14115339225b233fd78b92d64c62b6707ddba`。
- 候选 `session-continuity-r4-13c1b2e`：prepare 1.488 秒、verify 21.818 秒、promote 38.411 秒。安装器总计 38.242 秒，其中 snapshot/prepare 17.533 秒；不是多轮全量测试造成这次安装用时。
- 候选 receipt `04e7853d86e4d1bb269baf609395bedfd6f099a2afa2c306e4ce81d1e5c7f537`；真实 CLI/unified exec/PreToolUse 正反例通过。Windows/Desktop 不在此证据覆盖范围。
- production artifact 已发布到独立正式 artifacts 目录，不依赖临时 task worktree；deployment generation_verified，scheduler 16/16 loaded，failed/missing/retired 均为空。6 个 Sulde Hook 唯一、enabled、trusted。
- 当前旧会话 `01a04634-318f-7203-ba2d-26fa6ac442b0` 的真实负例在执行前被拒绝；marker 未产生，双代际 proof `ce75baa629cd3f27832970951abc14dbb944b526516f204ec473708e421ac67b`。其后 str.replace/list.remove 正常执行，普通 touch 成功，未锁住任务。
- performance 热路径内核与已通过的独立比较一致；详细数据及微小负收益见 r2 report。不能把微基准阈值通过宣称为所有 Agent 任务绝对不变慢。

## 仍未通过的旧会话验收

显式派生索引重建扫描 48,991,810 bytes，保留 91 行，invalid_rows=0、source_modified=false。当前已提交交接边恢复成功、authority_transferred=false；未改写原始观测或授权。

但当前会话存在多个早于本批安装的工作区转换：

- 最后可找到的真实 SessionStart 在 2026-09-07，workspace `6c307b1c…`；更早记录位于 `db613882…`。
- 本轮能独立恢复的当前交接只有 `1170bc6c… → d9f55149…`，没有覆盖到上述 SessionStart 所在的旧工作区。
- 当前真实 UserPromptSubmit 存在于 `d9f55149…`、旧 runtime `b16d452d…`，时间 2026-09-08T10:27:27Z；当前新 runtime 的真实 Pre/Post 对存在。
- `recover_current_transition()` 明确只恢复当前边。不能凭相同 session 或 Git common-dir 推断缺失旧边。
- 此外 `host_capabilities.py` 的 predecessor 选择要求所有缺失生命周期能力来自同一个旧 runtime。混合代际 SessionStart/当前 prompt 的场景仍需单独正反例验证；不能把现在的缺失链问题仅归因于日志尾部。

最终 doctor：artifact/scheduler ready，pre_execution_safety verified，effect_debt clear、Hook failures clear；interactive degraded，原因 host_interactive_fresh。这不是要求用户重启的闭环，也不宣称全部修好。原有生产交互降级尚未消除，但本次安装和真实 Hook 没有失败，未自动回滚。

下一步最小返修：用原始决策/执行审计重建已验证的历史多跳转换，覆盖多 runtime 生命周期证据；始终不生成 SessionStart、不转移权限、不在热路径回放全历史。需新修订和精确发布授权，不修改本次已密封发布件。本任务及工作树继续保留，不以安装完成提前删除。

## 执行过程问题（保留，不改写为成功）

1. 首次 cachebuster 调用多加了 `env`，且与读回命令放在同一编排单元；没有形成密封消费记录。内容变化由 Git/manifest 独立回读确认。修正为该 profile 规定的独立环境赋值调用后，以相同 token 幂等执行，内容未再次改变，真实 grant 消费和 verifier 才成立。首次调用不冒充密封执行。非规范编排为何未在前置入口拒绝，仍是独立审计候选，不在冻结 r4 中偷偷改守卫。
2. candidate promote 的 v2 adapter 接受的是 `python -B script ...`，与 cachebuster 环境赋值形式不同；带环境前缀的首次 promote 被 PreToolUse 正确拒绝，未执行/消费 grant。按已有代码和测试的精确 argv 执行后安装通过。后续宜从系统输出可执行 argv，减少 Agent 手工拼接错误。
3. 宿主再次报告保存精确 approval prefix，Agent 未请求 prefix_rule；不据此给任何后续修订授权。
4. 文档和证据提交发生在安装之后，只是状态记录，不声称后续报告 HEAD 已重新构建安装或全量测试。

## 证据保全与边界

本地完整测试日志和候选 state/receipt 已另存仓库根 `.sulde/data/guardian-session-continuity/r4-20260908/`，独立于 task worktree。归档包含通过和失败记录，不包含候选整套缓存或生产密钥。
归档 SHA256 `8501c6b1643d8a25b37c429edff994cb9e5c2080c322ce6fa276d71584bf1d9f`；从归档独立读取的完整测试日志 SHA256 `af12e30b37d9223e85b94e1dfa9ca8257b21a466d4bf38dfbf5cdc288715bbf8` 与原始摘要一致。候选 state/receipt 副本逐字节相同；文件均为 0600。
当前 root task 仍有历史连续性验收未完成，因此不运行完成锚或资源删除。main 的三项原有 `.ua` 修改保留，未推送远端。

沉淀候选：旧代际迁移不能只用单跳、单一旧 runtime 夹具验收多次升级过的真实会话。路由正例：有真实决策和执行证据的当前边可恢复；路由反例：仅同仓库/同 session 不足以补边。执行正例：恢复派生索引并保持源日志不变；执行反例：将已找到 SessionStart 误当成已证明它与当前工作区连续。观察缺口 verified；完整历史转换根因及补链策略仍需专门回归，不能自动沉淀为已经修复的事实。
