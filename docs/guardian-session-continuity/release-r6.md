# R5 补齐 / R6 本地发布验收

结论：本次冻结范围已通过开发、隔离候选及当前旧会话生产验收。
2026-09-08，未重开当前 Codex session，未回滚 main，未推送远端。

## 完成项

- 历史恢复：从已完成释放的两端原件恢复 2 条旧 task → dev 边；当前
  dev → task 边保持不变。释放摘要、完成摘要、provider/session、精确路径、
  时间顺序、并发 CAS 和签名索引都参与验证。
- 删除后的 worktree 使用释放记录内的物理路径身份，不再向上查找成主仓库。
- 不同旧 runtime 的 SessionStart 与 UserPromptSubmit 可以分别作为真实生命周期
  证据；必须同时有当前 runtime 的真实 Pre/Post，不能携带审批、grant 或效果债。
- 同一 session 的 Stop 跨 workspace/runtime 终止 prompt 活跃性。
- 历史扫描仅在显式维护入口运行；普通 Hook 仍使用有界只读投影。

## 版本与独立效果验证

- 实现：`34aa902473d5f4d83076c7426987751e0ae2319a`；开发报告已合入 dev。
- 已安装 source：`3422c9bc35339af1e007d42f8a291c31fc12aa98`，后续仅追加报告。
- 版本：`0.2.5+codex.20260908125544-42574b7af3`。
- runtime tree：`f869fe51d84883ea55f5c9c86b7a28d4101ade466537a80f4533b275a48260ac`。
- source/artifact/installed 的历史恢复模块 SHA 相同；artifact 与 installed
  generation 文件逐字节一致；deployment、runtime owner、launcher 同 generation。
- deployment=`generation_verified`、runtime owner=`active`，两者
  `operational_ready=true`；scheduler 16/16 loaded，无 failed/missing/retired。
- R6 Allow receipt：`a4e8fbaf10081ffcb115a1ce8b8eb363f5db763274c16489e50a1934f81c949f`。
- 新 cachebuster grant `7c5d9f44…`、install grant `4ef6490f…` 各消费一次，分别由
  `tool:codex_plugin_cachebuster_verify` 与 `tool:codex_plugin_install_verify`
  结算为 system_verified。pending/open/integrity breach/pre-execution gap 均为 0。

## 当前旧会话的真实结果

原 session `01a04634-318f-7203-ba2d-26fa6ac442b0`：

- doctor 与 operational readiness 均为 `ready`，reasons 为空。
- SessionStart 原始时间仍为 `2026-09-07T03:24:19.121562+00:00`，来源 workspace
  仍为 `sha256:6c307b1cba6b40cc9ad0a7c1`，不是新造一次启动事件。
- 本轮 UserPromptSubmit 原时间仍为 `2026-09-08T11:16:04.380943+00:00`；
  它与 SessionStart、当前工具 roundtrip 分属三个 runtime 身份，分别验证。
- 四份历史源/完成合同前后 SHA 全部相同；当前会话 mapping 摘要未改变，
  `authority_transferred=false`。没有转移旧权限或抹除未知效果。
- 新发布件的真实 PreToolUse 在执行前拒绝负例，marker 未产生；紧接着的
  普通本地 touch 返回 0。没有触发全局暂停，也没有降级放行。
- 生产 proof：`b8a01c566e90e59506baeaf2eedfba54a7d808985d2d4d4c456fd335c46cb1c6`。
  denial event=`fe3f8abc338935fee75a384f`；绑定本次完整 artifact generation 和
  loaded-module=`6092aeb36ec1863e162590620aa14115339225b233fd78b92d64c62b6707ddba`。

## 测试、时间与证据

开发共 384 项影响范围测试（367 pass / 17 既有跳过），两条真实连续性用例、
两项固定预算 benchmark 均通过。完整逐项和正负性能变化见 supplement-r5.md。
没有将 R4 全量结果冒充 R5 exact-tree 结果，也没有因版本后缀再次重跑全量。

正式候选 prepare 1.273 s、verify 41.134 s、promote 34.402 s；安装器 total
34.306 s，其中快照阶段 15.558 s。候选期间没有加载生产 launchd 标签。

证据独立归档在仓库根 `.sulde/data/guardian-session-continuity/r6-20260908/`，
四个文件权限 0600；包含完整测试日志、候选 state/receipt 和生产回读。
归档 SHA：`37992267d4f39faf7b53fbe0ab32029fc2bef4c06c4bf682e87677dff41657be`。
归档中四份 output.log 与原测试摘要逐一一致，候选副本逐字节一致。
原始控制/效果日志继续保留在原位置，未移动或删除。

## 边界与资源退出

不宣称 Desktop/Windows live、任意缺证据的历史 handoff 或“删除活跃宿主 cwd”
已经解决。探索性测试确认中途删除宿主 cwd 会使 Hook 启动失败；通过的真实测试
使用持久宿主根目录并正式切换下一 turn 的 cwd。这个失败及范围限制没有隐藏。
清理前已用 lsof 独立检查任务目录，没有活跃宿主占用，仅观察命令自身。

产品验收与文档先提交合入 dev；随后由 Agent 结束 Skill、执行正式 workspace
release、普通 Git 删除已合并任务 worktree/分支，并回读原生 completion receipt。
资源退出的最终真值是该 receipt 的 `workspace_cleanup.status=complete`。
main 原有三项 `.ua` 修改保留；不清理其他任务资源或生产回滚快照。

本次由 plugin-creator 官方 helper 与事务候选流程发布，没有手工编辑 marketplace、
cache 或 LaunchAgent。历史路径身份经验保留为补齐报告中的沉淀候选，未额外扩写知识库。
