# Venv identity 正式发布验收

状态：正式安装及本轮限定 live 验收通过，已合 dev，证据已归档。capability_tier: deep。

## 冻结范围

- 基线 dev `5b53d1486852b213c98ddc89cbcff45ecbe42fd6`；源码修复 `f6fa07f`。
- 上轮限定回归 365 total、348 passed、17 existing retired skips；新增 7 项全部通过。
- 只改官方 cachebuster 版本字段和本报告；运行源码不改。
- 官方 candidate prepare/verify/promote 一次；使用已核验实际 Python
  `/Users/eric/.pyenv/versions/3.10.7/bin/python3.10`（3.10.7、PyYAML 6.0.3）。
- 当前旧守卫仍有 venv 识别缺陷，不能用它完成该路径的自举发布；先用已验证的实际
  Python 发布，再验证新 installed runtime 的 venv 识别。不同环境不用旧回执。
- 安装器只重载原有 16 labels，保留定义和 RunAtLoad；不额外 kickstart、不新增模型调用。
- 安装后验收真实入口、当前 lane doctor、fresh stdio MCP、真实 Hook 负向证据；
  另建一个只用于 prepare/verify 和新 runtime 只读识别的 venv 候选，不第二次 promote。
- 不把识别成功说成 venv 生产安装已执行；不把当前 lane ready 说成全局历史债务清零。
- 不 push、不合 main、不清全局告警、不手改生产缓存/历史账本、不安装新依赖。
- 任一发布门失败保留原始证据并停止；成功后只合 dev，归档并官方清理本任务。

## 前置依据与控制

准备 revision receipt `8b847bafd34ba4e49cf25825f8fc129c680c9ef3509d4ed26b1a44b83c38ca45`；
worktree handoff receipt `0ff5011e1c523ac7f53ff31efd47f864b38b3a2fea72a6a773fe3baacaa6a2db`。
当前已安装 `0.2.5+codex.20260913092700-3918bd5f72`，官方 marketplace helper 验证
实际配置为 sulde-local。默认 personal marketplace 不存在，未创建；使用 CLI 解析出的
现有本地 artifact marketplace 路径成功核验。当前调度只读检查 16/16 ready。
kb-search 命中 ap-0252/ap-0224，原文已全文读取：固定实际解释器、分开模拟与 live 证据。
根 main 的既有 .ua 三文件修改和 .sulde/ 不在任务范围。

## 执行问题记录

- Agent 的首次 handoff preview 错用 target=current，结构校验拒绝；改用已注册绝对
  worktree 路径后原生批准成功。未发生错误映射或生产写入。
- 首次文件检索误列不存在的目录，以及 zsh 未匹配 glob；均只读失败，改为实际路径检索。

## 证据目录

`.sulde/public-export/venv-identity-release-20260913/`。候选状态、回执及失败记录保持原样。
回滚仅由官方事务安装器恢复原部署；不以重试或手改账本代替独立效果核验。

## 正式执行结果

原生安装 revision 3 receipt：`5e46576ed17f1a9d9445a2635c5e3a16857e7b51cd4e5e85da4ecb3fa045cb62`。
官方 helper 消费一次、validator exit 0；版本提交 `a4edf7a660b10522a8ad09e619e31cc47064fdf6`
只有 manifest 版本一行变化。运行源码与已验收 dev 完全相同，没有新增修复。

已安装版本：`0.2.5+codex.20260913114101-2f3efad2b6`。
runtime tree：`ae2954966c48cb83791ac7e44a283e7283beabcad290d36f6e2ed927b4f6a2db`。
plugin tree：`a3c62d9cd1ec531ba5f8809bd7f6d3f6b3c773109e0c9ddf8c33fd5c80249b00`。
实际 installed cache 与官方 artifact 递归逐文件比较一致，exit 0。

| 候选 | prepare | verify | promote | 终态 |
|---|---|---|---|---|
| vir-canonical-20260913 | 27.286 秒 | 18.096 秒 | 45.635 秒 | promoted，单次消费，error=null |
| vir-venv-check-20260913 | 1.176 秒 | 19.726 秒 | 未调用 | verified，未消费 |

两候选使用同一源码 commit/tree，artifact runtime/plugin 摘要相同。两个 verify 均在
已获宿主权限的隔离环境执行，没有 EPERM 或验证失败。canonical 准备较慢的具体阶段
没有足够分段证据，不将该 27 秒推断为守卫故障；安装器内 snapshot/prepare 23.630 秒，
total 45.514 秒。人工等待不计作这些执行计时。

canonical receipt：`333c01c41b46cd8a2732e811ae5562f0da85620529b55642ee2ecad9f9b971a0`。
venv receipt：`2ffaaeabf44c582bfbe3c8a7bab5d274cfbe5fa79dd03b5c16281cae900a0cc4`。
helper attempt `att-46a6a529da642b03bf33c30b` 与 install attempt
`att-c5942393d916d9ccc46a6c58` 均已 system_verified；安装独立核验时间
2026-09-13T13:23:15.806220 UTC。没有复用旧任务或旧环境回执。

## 安装后现场验收

- 当前 lane doctor：operational ready、reasons=[]、配对 settled=true（不再需要确认）、
  unsettled=0、cas_mismatch=0、effect clear、Hook failures clear。
- 原 16 labels 的 launchctl 真值 16/16 ready，failed/missing/retired 均为空；没有额外
  kickstart。这不是所有后台业务任务重跑成功的声明。
- 真实当前会话 Hook 拒绝 canary 删除；官方 finalize 证明未执行删除并机械清理 marker，
  随后 test 确认不存在。proof `08e241f946385427d569a349f6130f6d7a103897b7c459e76c2c471d883d9f44`，
  doctor 显示 proof_current_generation=true，2026-09-13T13:39:38.926768 UTC。
- 全新 installed run-mcp.sh 进程：initialize/tools/list/kb_status 三请求通过，8 工具，
  exit 0。snapshot fresh，但 background degraded 原样保留；不是替换现有长连接 MCP。
- 系统 Python 真实只读 status 正常输出 JSON，missing_sources=[]、launcher 健康，
  无 TypeError；整体 exit 1、ok=false、warn=true，因历史告警，不记为全局健康。
- 对真实 venv verified receipt，用新 installed resource_preflight（非工作树模块）
  无 mock 调用只读识别器：v1/v2 均通过，仍绑定 resolved binary；state/receipt 字节
  前后一致、promotion_consumed=false。没有调用 native-decision 或第二次 promote，
  不将该证据说成 venv 全链生产安装已执行。
- 本轮未重跑全仓 suite；复用上一源码回归，新增真实候选与上述现场验证。

安装器最初 restart_required/native UI unobserved 等原始结果不改。当前线程已独立
证明新版 Hook；本轮交付不需要强制重启。若要加载新的 Skill/工具目录，应在新线程
试用，不把 catalog 刷新和当前 Hook 就绪混为一谈。

## 遗留与边界

- `promote --help` 被旧 Guardian 当作未密封维护调用执行前拒绝，未产生安装效果。
  Agent 转而只读源码确认参数；本轮不修该误拦截。
- Agent 曾用不存在的 pre-execution 子命令查询帮助，argparse 拒绝；按实际
  pre-execution-proof-prepare/finalize 完成，未伪造证明。
- 全局 effect_blocking=167、interventions_open=151、event_contract_violations=275；
  上轮为 274，未逐事件查归属，不能声称这一项没有增加或是本轮导致。
  heartbeat generation 仍 self_fixed_sections_changed，既有同步/历史状态不在本轮清理范围。
- 知识库规则只影响固定解释器及证据分层；没有写共享 KB 或图谱。venv 根因的 Layer1
  沿用 [源码修复报告](venv-promotion-identity-20260913.md)，不重复入库。

## 核心归档校验

- installed-doctor.json：`728c7be44a58435f1b1ecbbe39e90de7216ea0da3ce1ddd5caae4dbb970edabf`
- venv-recognition-result.json：`89a2fdc024da9646f36ed4e6bb16632ea35663f68cf502560894028fe2a6dade`
- live-pre-execution-proof.json：`dcd3bf8d805423f542cb1ca523b2834e5347675b06316a6e4a48ea99d3bc036f`

归档包含两个原始候选及现场检查脚本/结果；旧路径不重写，不把归档当作可重放权限。

交付提交 `fc3d6bf` 已 fast-forward 合入干净 dev；仅本报告后续补记，不改受测运行源码。
131 MiB 证据已完整复制到长期 dev worktree 同名目录，`diff -qr` exit 0；当前 main
用户修改保留，未推送、未合 main。临时 worktree 的最终清理以官方 release/finalize
独立回执为准，不预先宣称删除成功。
