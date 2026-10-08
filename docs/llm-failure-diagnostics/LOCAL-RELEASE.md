# LLM 诊断修复：本地安装验收

2026-09-23。指定范围安装与实际链路通过；不是全系统健康闭环声明。
本报告形成于 dev 快进及远端推送前，Git 推送结果以之后的远端回读为准。

## 版本与证据边界

- 源码 `7d3c309aa2053d2e5a2dca254cb433743e6b62c3`，基于 dev `d01920f`；
  两者仅 plugin.json 的官方 cachebuster 版本字段不同。
- 正式版本 `0.2.5+codex.20260923135758-a1d7cd1c4c`。
- runtime SHA-256 `cc7bbfa9b9b696c81bdd1af8cfdea050f430c3733e7a5f6ef4d7ec95d84b6c79`。
- 本报告/JSON 是安装后的 docs-only 提交，不声称安装来自后续文档提交的 exact HEAD。
- 结构化凭据：[LOCAL-RELEASE-evidence.json](LOCAL-RELEASE-evidence.json)。

## 实际执行

1. 原生 revision 2 审批后，plugin-creator 官方 helper 更新版本；结构校验、diff-check 通过。
2. 候选 r2 prepare 2.415 秒，verify 20.304 秒；真实 CLI/Hook/unified exec 正反例、
   候选 MCP、隔离调度入口通过。候选未观测项没有冒充生产验收。
3. 精确密封 promote 执行一次，exit 0，generation_verified；安装器实测 55.016 秒，
   其中 snapshot_and_prepare 为 31.234 秒。没有重跑全量或调用真实业务模型。
4. 当前旧 session 的真实 `rm` canary 被 PreToolUse 提前拒绝；finalize 同时绑定模块与
   artifact generation，proof 为 `82635123b766ac408a8316dd19daa1772c672d5f212e5d32c307a480ffe81733`。
   probe 使用 prepare 创建的专用哨兵；不是删除业务文件，finalize 管理其清理。
5. 宿主外 doctor：scheduler 16/16 loaded，failed/missing/retired 均为空；
   两笔 cachebuster/install 效果经 system verification 结算，pending/open event/effect debt 均 0。
6. 已安装配置投影启动新 MCP 进程：initialize、tools/list、kb_status 三次真实请求通过，
   8 个工具；不声称当前对话已重新连接 MCP。
7. 两个入口与新增 helper 的 source/artifact/installed SHA 全相等；回读先前测试的全部
   源码、测试和运行器摘要一致，复用 82 passed/2 Windows skipped 及源码/产物各 44 项检查。

## 失败与未观测事实保留

- 第一候选 prepare 在 `codex plugin list` 的 30 秒超时处失败；无 promotion。
  只读查询恢复后，用新 ID 有界重试一次成功。不能据此断言网络根因或抹掉失败候选。
- 两次 promote 调用格式不匹配，在 PreToolUse 被拒，未消耗安装效果：一次缺少显式
  candidate/kb home，一次多了环境赋值前缀。读当前解析器后使用它支持的精确 argv，
  保留 `-B`；入口自身设置禁用 bytecode。未放宽规则或绕过守卫。
- 安装结果初始为 scheduler_ready_live_host_unverified；后来取得本会话真实 Pre/Post
  及双 generation canary，不改写安装器的历史初始结果。
- 当前 session_context 为经验证延续，prompt_control 尚无新 generation 观测，
  doctor interactive 仍 degraded。不能合成 UserPromptSubmit 或宣称新线程验收已完成。
- MCP transport_passed 不代表后台生命体全绿：kb_status 返回 fresh 的 degraded 背景快照。
  本次不修改历史快照/账本，也不扩展至无关后台问题。
- 静态 Skill catalog 刷新仍需新会话；当前会话的真实工具拦截已验证。
- Windows 原生、真实服务商失败、完整生产 annotation/backfill 不在本次证据范围。

## 工作流与沉淀候选

使用 dispatch-task/intent-guardian 限定发布任务；plugin-creator 要求官方 helper 与
事务安装；kb-search 的 live-session 热更新反例要求保留旧静态树并另验真实 Hook。
main、正式知识库/记忆内容、Orca 环境与其他任务工作树未作任务性修改。

候选 1（verified 现象、根因 inconclusive）：全目录插件枚举可使本地 prepare 超时；
路由正例为本地安装前置目录枚举超时，反例为 artifact 结构损坏；执行正例为保留
失败候选、只读回读后新 ID 有界重试，反例为持续重复安装或修改生产配置掩盖失败。

候选 2（verified）：密封提升入口要求精确 argv，等价环境前缀不被该解析器接受；
路由正例为执行前命令绑定拒绝，反例为 grant 已消费后的真实安装失败；执行正例为
读取正式格式并保留参数绑定，反例为放宽识别或重用已消费 grant。未直接写入知识库。
