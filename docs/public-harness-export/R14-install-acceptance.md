# R14 正式安装与 live 验收

日期：2026-09-13。承接 [R14 源码修复](R14-status-python39.md)。

## 结论与停止线

**R14 已通过官方链安装；生产 Python 3.9 健康检查的受保护身份读取 TypeError 已消失。**
当前会话 interactive ready、pairing settled、effect debt clear；实时 scheduler 16/16 ready。
这不是全局历史健康问题全部关闭，也不是所有后台业务重新执行后的验收。

冻结基线 `edde8597a773d9af3b8cfa8f01a43949e7f225f3`；发布提交
`8dd5e9e59e8c22d33791e859f9a69fdbe05a334e` 只更新插件 manifest 版本。
本报告为安装后文档，不改变已安装源码身份。没有新增运行时代码修复。

本轮范围：官方 cachebuster 一次、candidate prepare/verify/promote 一次、安装后只读
健康/MCP/doctor 检查、真实 Hook 负向测试、报告及本地 dev 集成和临时资源清理。
安装器按既有策略重载原 16 个 labels，允许原有 RunAtLoad；未额外 kickstart
auto-sediment、heartbeat 或同步任务。未推送远端、未合 main、未直接编辑生产 cache/账本。

## 控制与发布身份

- 发布准备 revision 2：`b9dfa7b935b905ff33d9aeb6aa1d5cc0e391e3b528339ed875022fd2420a329c`。
- 原生 worktree handoff：`e4794194fb67fe32e243726b1deabf1b164b848218d094f3754045df70fe7090`。
- 正式安装 revision 4：`94b6f6147a58f11d0b77c1ad5090807ffeef6df1cbed0d5f73477c96a8434bcf`。
  transaction `ndt-157acf7d089f5b0181aeeeb42ccc39a6`。
- 安装 grant `54442fb83813af5faceb02e9b786642e69d6b9a944d8daad89cf55f566dedcb8` 消费一次。
  helper 仅执行一次，版本 diff 和 plugin validator 通过；runtime continuation_uses
  只列安装消费，不虚称其中也存在 helper 的独立消费记录。

| 项目 | 值 |
|---|---|
| 版本 | `0.2.5+codex.20260913045930-43f6e3c807` |
| Source tree | `f1b60360bcaf9ffa5e86b4418c854d277668d2b6` |
| Runtime tree SHA-256 | `c2a22c0cf060609832310cb679faa4d95ba870ca3eebc704ec8ff4abf159932a` |
| Plugin tree SHA-256 | `a75e8752c0c50a0a28914d33e9350b6d14be4829fca9546591f3e750c9ebb724` |
| Candidate | `r14-python39-20260913`，promoted，promotion_consumed=true，promotion_error=null |
| Canonical verification receipt | `4eaaa2925ba13d1e573a4f878d989d088914a404f0445555bd2120e71c652d39` |
| Candidate prepare / verify / promote | 1.530 / 19.369 / 38.028 秒 |
| Installer internal total | 37.861 秒 |
| Scheduler activation | `ad43dc11a58d4802958b7acdc66f199f` |
| 安装效果 | `att-bf443e70b0bf6f1f07f8b789`，codex_plugin_install_verify 独立结算 |
| 效果核验事件 | `71f76b6fa4dab5cfdf02dd4f`，2026-09-13T06:18:04.667241+00:00 |

当前 marketplace 名称经官方 helper 验证为 sulde-local；安装链发布对应的新本地制品。
已安装插件与官方 artifact 递归逐文件比较一致。修复文件源码/安装态 SHA-256 均为
`c945c57db8e61461ac2ab863b7de93114703af8e254adf1a43d309925017df92`。
原版本按官方策略保留为 controlled retired alias，未手工清理历史 runtime。

## 安装后真实验收

1. 系统 `/usr/bin/python3` 3.9.6 执行正式 runtime 的
   `scripts/kb/sulde-status.py --json --read-only`，06:19:35 UTC 收集结果：
   - missing_sources=[]、launcher_contract_healthy=true。
   - operational_readiness=ready / interactive；scheduler_health=ready，16/16 loaded，
     failed/missing/retired labels 均为空；不再返回 TypeError 或 scheduler_projection_unavailable。
   - 顶层 ok=false / warn=true 仍保留。该入口只读模式不发布快照，且仍含历史/其他健康告警，
     不能用管道最后 jq 的 exit 0 声称全局健康成功。
2. 当前会话真实 PreToolUse 拒绝删除测试 marker；finalize 证明 marker 保留后清理，
   末尾独立确认不存在。不是模拟 Hook，也没有把 prepare 的创建说成零写入。
   proof `436f9f11c7895c462311c56e9d2f26dd354d30132732d4640b0c4cc8bac74551`，
   started event `e927625e06717d47beca0f11`，绑定本次新 artifact generation。
3. 独立宿主 doctor：当前 lane bound，interactive ready；unsettled=0、cas_mismatch=0；
   当前 blocking/pending/interventions=0；Hook failures clear；scheduler ready。
4. 从新插件的 `run-mcp.sh` 启动新 stdio 进程：initialize、tools/list、kb_status 共 3 请求，
   8 个工具可见，协议和工具调用通过。后台 snapshot fresh，但 degraded；生成时间
   06:18:19 UTC。没有声称替换当前对话早先的 MCP 进程。

候选中的 native_permission_ui 和 scheduler_host 保持原始 unobserved；安装器完成时
live_host_unverified 也保留原值。以上后续现场证据独立记录，不改写旧回执。
静态 Skill/工具目录可在新线程验证加载；当前会话 Hook 实测已经完成，不需要为此强制重启。
沿用 R14 的 29/29 与 42/42 源码专项证据，没有声称本轮新跑全仓 release-level 套件。

## 明确保留，不自动扩为任务

- 最新后台快照仍黄，LIFE 状态 degraded；R14 源码报告中的心跳 SELF 内容漂移仍未处理。
- 本次全局只读收集显示 effect_blocking=167、interventions_open=152、invalid_stores=7、
  event_contract_violations=270。它们不等于当前会话的零债务；未逐个复核来源和历史时序，
  不能断言本次新增或已全部解决，也不能拿旧 Python 失败前的零值当作全局无债务证明。
- 同步 migration_required 和迁移写入器的 Python 3.9 兼容限制均不在本轮修复范围。
- 未通过真实写业务重测所有 scheduler labels；本轮证明装载/退出状态与只读入口，不重复
  R13 的沉淀业务，也不自动触发任何额外模型调用。

## 执行问题与收尾证据

- 第一张安装卡只声明 local_write，虽有人类可读安装描述，却只生成 cachebuster grant。
  在任何版本更新/安装之前回读发现；补齐 external_write 声明并重新原生批准 revision 4。
  revision 3 未消费 helper/install；未绕过 typed effect 边界。该返工是本轮 Agent 参数遗漏。
- 生成修订提案时沙箱不允许写生产控制锁；按宿主原生许可重试提案生成，未直接编辑锁或账本。
- helper 使用提案已密封的固定 cachebuster（发布协议需要未来 tree），没有随意改 token。
- 遵循 intent-guardian 的原生批准与独立效果结算、plugin-creator 的官方更新链；KB ap-0235
  用于约束实际安装入口验证，而不是把源码测试当作发布通过。

原始候选目录与只读 MCP 脚本收尾时归档到长期 dev 的 `.sulde/public-export/`，原名保留，
原 state/receipt 内的历史路径不重写；它们不是可重放安装授权。

| 相对归档文件 | SHA-256 |
|---|---|
| `r14-install-candidates/r14-python39-20260913/state.json` | `3bc8cb40c4332d96ac17761b8dcd900fcd59258341544b136dcb91453447c999` |
| `r14-install-candidates/r14-python39-20260913/verification-receipt.json` | `ae8ce4b8770e930e874c70697aecb7cbc635f4515f62998773c16906d0aa5551` |
| `r14-install-mcp-check.py` | `33ab0e7c77cdf9ba95814a6dafb1147899b96b20718b2ce17f269896e80b0ce5` |

没有新增独立沉淀主题：本轮安装证据补足 R14 原候选的生产验收边界，未直接写知识库。
