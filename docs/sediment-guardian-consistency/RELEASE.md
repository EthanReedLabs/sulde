# Guardian 知识沉淀本地发布

本批六篇新增、两篇并入现已发布到本地 Sulde。此前 README/EVIDENCE 的
“未合并、未安装”描述属于文档验收阶段；本报告记录用户另行批准的发布阶段，
不覆盖旧证据或把失败记录改为成功。

## 发布与知识验收

- 已验收知识提交：`e921807a4a4d8aeb1ff08631d2840974f20f9f8a`，先快进合入 dev。
- 官方版本号变更在独立发布分支提交为 `0c9aabc29caf79074d21fd191c8812087d794691`。
  物理工作区不变，未直接在 dev 提交任务修改；收尾再快进合入 dev。
- 安装版本：`0.2.5+codex.20260911043115-19fde00701`。
- 候选 prepare/verify 期间生产未切换；通过后 promote 一次，安装为 generation_verified。
- 源码、artifact、installed runtime 的知识 MANIFEST 摘要一致。
- 官方增量建索引完成：387 篇、1,846 chunks、216 edges；更新 8 篇、删除 0、缺失关联 0。
- 经 `codex mcp get sulde_kb --json` 解析当前正式配置，启动真实 stdio MCP 新进程，
  完成 initialize 和 16 次 tools/call。8 次 kb_search 全部 top-1；8 次 kb_get 成功，
  正文与源码、installed runtime 逐字节一致。未直接调用 server 函数或伪造结果。
- 当前会话正式 Hook 负例在 PreToolUse 拒绝；独立 finalize 校验 marker 后清理测试标记。
  proof `34527ec458e5c55237ed7fe33bc6708ac58f061f18c0c9e1f4ba16d7c7a6bf6a`，
  started 事件同时绑定 loaded module 和 artifact 两种身份。
- 当前会话 doctor=ready、interactive=ready；scheduler 16/16，无失败或缺失；
  两张一次性 grant 各消费一次并由独立内容 verifier 验证，effect debt=0。

没有改动运行逻辑。沿用原 32 条改写检索、20 条基准及知识工具/消费者定向测试证据；
未重跑代码全量。另做本次候选验证、真实 Hook、MCP 和内容摘要校验。

## 必须区分的旧会话限制

当前对话已启动的 MCP 进程仍指向旧 runtime。增量索引更新前报告 doc_id not found；
更新后报告旧 retired runtime 中正文文件不存在。这是实际失败，不能写成旧连接已热更新。
新启动的正式 MCP 进程全部通过，但本轮没有重连当前对话的 MCP 客户端。
新会话或宿主支持的 MCP 重连会重新加载当前配置；Hook 已在当前会话独立验证，无需
为 Hook 重启。静态 Skill catalog 沿用宿主加载规则。

后台 kb_status 仍显示独立 degraded 快照，并暂报旧的 381 篇；直接读取生产 SQLite
确认是 387 篇。本批未修复后台状态缓存，也不声称生命体全域健康。

## 时耗与实施问题

官方 prepare 2.227 秒，隔离 verify 26.872 秒，promote 52.546 秒；安装器内部
52.385 秒，其中 snapshot/prepare 28.062 秒。增量索引 2.18 秒，实际 MCP 验收
2.067 秒。以上是进程执行时耗，不包含人工审批、排查和会话整体耗时。

首次创建发布分支和准备候选受文件沙盒限制，获得宿主授权后完成。首次 promote
省略了密封解析器要求的显式 --candidate-home，被执行前拒绝；补齐既定调用格式后
只消费一次原有效 grant。控制命令与只读/help 组合也被预拒绝，拆为独立调用完成；
未修改策略。误用不存在的 canary 帮助子命令没有效果，随后使用正式 prepare/finalize。
宿主再次报告保存精确 native-decision 前缀；调用没有传 prefix_rule，根因未确认。
这些现象保留为工作记录，不在知识发布中顺带修复。

## 技能与保留边界

使用 sediment 完成判重、脱敏、六新增两并入和可消费性验证；plugin-creator 要求
官方 cachebuster、既有 marketplace 与事务安装链；intent-guardian 用本会话原生
Allow 和两张一次性 grant 绑定本次发布，没有移交旧权限或清除历史审计。

main 和用户既有修改未动，远端未推送，其他沉淀任务未合并或修改。
完整有界结果见 [RELEASE-EVIDENCE.json](RELEASE-EVIDENCE.json)，实际 MCP 验收入口见
[verify-installed-mcp.py](verify-installed-mcp.py)。这些收尾文档不改变已安装运行逻辑或
知识正文，不需要为了报告再次安装。
