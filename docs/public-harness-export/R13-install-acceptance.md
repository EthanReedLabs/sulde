# R13 正式安装与 live 验收

日期：2026-09-13。承接 [源码修复报告](R13-auto-sediment-source-binding.md)。
意图 lineage：`guardian-p0-supervised-delegation-20260815`；当前会话原生 workspace handoff
后，以 revision 196 批准本轮发布范围。未继承原合同的执行 grants。

## 结论

**auto-sediment 源码仓绑定修复已正式安装，并通过一次真实定时任务验收。**
R12-F01 的安装路径阻塞可由本报告关闭。当前会话 interactive ready、effect debt clear、
native pairing settled；实时 scheduler 16/16 ready。未将这些结果扩大为全部后台功能验收。

正式源码提交为 `567e630f5c120ef96892c8ab970d51fe32cadd63`：在已验证的
`a632508cd76f3ffd210c96cf6c4dc7924db108a1` 上只更新 Codex manifest 版本。
本报告是安装后的文档提交，不改变已安装源码身份。

## 发布身份与执行证据

| 项目 | 结果 |
|---|---|
| 已安装版本 | `0.2.5+codex.20260913033534-16c367e5e7` |
| 源码 tree | `d5b0fc8881299beafd7bde77e1c07a6fb0c48975` |
| Runtime tree SHA-256 | `caa078aa37d1bf10092f249632b9840883c7e4c24321356170775b1d09ff4641` |
| Plugin tree SHA-256 | `6f0414dc206bccb037b19b8eac79d9390d8ad76be18a57cb6f3d89de8a49a25b` |
| 正式候选 | `r13-auto-sediment-20260913-host`：verified → promoted，`promotion_consumed=true` |
| Candidate canonical receipt | `923e5b3aeb12211441b5f23d168bcb3aa4c4d1eb03eed413bb3de0fa86acf034` |
| 验证 / 安装耗时 | 候选验证 19.305 秒；安装事务 37.599 秒 |
| 安装效果 | `att-de71f976857705db801b4666`，由 `codex_plugin_install_verify` 独立结算 |
| 安装 grant | `06e5a6df8fa4749ed7fb2a86dfd38f6b391ec11c0332b8bf07595c45580032f7`，消费一次 |
| Scheduler activation | `5ec447e8e3d54ef4a695cae126de2c92` |
| 制品与 cache | 官方制品与已安装插件递归逐文件比较一致，无直接 cache 编辑 |

新版通过官方候选/事务安装链发布。原制品由安装器按既有策略保留为 retired alias，
未手动删除历史版本、修改账本或绕过批准。安装器完成时的 `live_host_unverified` 原值
保留在原始回执；其后的真实 Hook 证据单独记录，不伪改安装回执。

## 绑定配置与真实业务结果

`SULDE_KB_HOME/auto-sediment-source.json` 新建，权限独立回读为 `0600`：

- `schema=sulde-auto-sediment-source-v1`。
- `source_root` 为长期保留的 `.worktrees/guardian-v3-dev-merge`（dev），不是本次临时发布 worktree。
- `git_common_dir` 为本仓库 `.git`；绑定值经 Git 只读查询核实，未触及 main 工作文件。
- 配置 SHA-256：`046af44cd1109eea01609c605dc04af479c37795f7574a17144f36b2ebfe4940`。

仅执行一次 `launchctl kickstart gui/501/com.sulde.auto-sediment`，未使用 `-k`，未重试。
触发前新 generation 的 `runs=0`；完成后 `runs=1`、`last exit code=0`、not running。
实际入口仍为既有密封 `sulde-scheduled-run`，使用 `/usr/bin/python3` 和新 runtime，
参数仍为 `--max-candidates 5`，无 scheduler 定义更换。

本次 run：`20260913-114256`，约 11:42:56–11:45:06（北京时间）。

- 处理真实候选 5 条，原文件行号（零起始）209–213；不是空候选或注入合成候选。
- 触发前对这 5 条 lesson/context 运行现有密钥模式扫描，命中数为零；仅输出计数和摘要。
- 最终 `skip=2, unsure=3, new=0, merge=0, branch=none`。
- 两条已覆盖内容标为判重跳过，三条因缺少一手证据保留人工判断；没有将它们改成“已沉淀”。
- 五条决策与候选标记逐项匹配；待处理候选 345 → 340；无执行失败/超时回退理由。
- 源码 dev 工作区仍干净；本轮 runtime 临时 worktree 已自动清理。

本次没有 new/merge，因此没有生产知识新文档或审查分支。本报告只证明真实判定、
判重/留人工、标记和工作区生命周期已运行；内容创建/提交路径的证据仍是上轮 22 项
合成专项测试，不虚称该路径也经过本批 production live。

决策文件：KB home 下 `sediment-runs/decisions-20260913-114256.jsonl`，共五条；
SHA-256：`9a6d0c226b4d51c0449450c03ca2dc9ee89a9a779e1408fef52836ca14594eeb`。
候选文件前/后 SHA-256 分别为
`5dd912194959749d2cf826e21fd99e206798a12efd8987c454d698d8a4c96c65` /
`ff8b0ed5c6c77d2248b3235e290b0820d9579f62d8561de2392a52342e272b35`。
原日志和决策内容保留在生产 KB home，未复制到报告或公开发布。

## Hook、MCP 与状态分域

- 当前会话真实 PreToolUse 拒绝负向 canary 删除；prepare 创建 marker，finalize 验证保留后清理。
  proof `b0c7bba211ba725f6d6c5ab0c7b755d0d6d575010c2764a372d6c50496aa5886`，
  started event `585542b90fdcdb0b4227757c`，绑定新 artifact generation。
- 实时 doctor：interactive ready；当前 session/task lane bound；pairing settled、unsettled=0、
  cas_mismatch=0；effect blocking/pending/interventions 均为零；hook failures clear。
- Scheduler 分域：ready，16/16 labels loaded，无 failed/missing/retired label；这是本机实时
  launchctl 证据，不是隔离候选的 scheduler dry-run。
- Codex `mcp get sulde_kb --json` 指向新版插件。按该 stdio 路径启动新进程，完成 initialize、
  tools/list、kb_status、kb_get 四个请求；8 个工具可见。ap-0235 原文字节与源码、runtime
  一致，内容 SHA-256 `0e50054d432dcf68b7f16c09a4451bf346c8a1db212e78d6249bfb08ed35ca58`。
  这不声称重连了本对话原有 MCP 进程。
- **保留限制**：kb_status 成功返回，但其后台快照仍为 `healthy=false` / degraded；该快照
  生成于 11:42:05，早于本次业务 run，不能覆盖后续实时 scheduler 检查，也不能据此宣称
  全局后台已全绿。其余健康维度和下一次快照刷新不在本轮强行修复。
- 新会话可验证新版静态插件目录加载；当前会话 Hook 的实测已经完成，不要求为该结果重启。

## 中途问题、恢复与原始证据

1. 安装卡预检最初仍按 session 绑定的 main 找发布文件，报 explicit release input unavailable。
   只读确认文件在新 worktree 存在后，走现有原生 workspace handoff；未修守卫或更改 main。
2. 默认 Python 的插件校验缺少 PyYAML；改用卡片已绑定的 Python 3.10.7 后验证通过，未装依赖。
3. 第一候选 `r13-auto-sediment-20260913` 因沙箱 `Operation not permitted` 验证失败，
   `live_preserved=true`。候选禁止原地重验；保留失败槽，创建同源码 host 候选获准验证。
4. 首次 promote 命令带冗余 `--codex` 和相对 candidate-home，不匹配精确密封入口，在
   PreToolUse 被拒绝。检查正式解析器后使用其规定形式，由回执读取已绑定 Codex 路径；
   未重复发生安装。未通过修改解析器或降低 unknown 策略来放行。
5. canary finalize 首次缺少 probe-id，参数检查拒绝；补齐同一 probe-id 后正常结算，未重做 canary。

两份候选目录和只读 MCP 验证脚本已移入长期 dev 的 `.sulde/public-export/` 原名归档，
约 106 MiB，迁移前后以下 SHA-256 一致。内部原始绝对路径保留为历史来源，不改写密封
state/receipt；归档不是可重放安装授权。生产安装独立效果已结算后才执行证据迁移。

| 归档文件（相对 `.sulde/public-export/`） | SHA-256 |
|---|---|
| `r13-candidates/r13-auto-sediment-20260913/state.json` | `33e15577c989e635965b2ed7828d45c72206c0469ba5e04c77b598aaa44773a1` |
| `r13-candidates/r13-auto-sediment-20260913-host/state.json` | `663bdabf1ffa3aa24e9413762d6c392a2ef1e96f5ab91503137465555d6f4dca` |
| `r13-candidates/r13-auto-sediment-20260913-host/verification-receipt.json` | `94b387e2b34c912cdc4fb6a744ba211869dcc9c38e3d30f7829f72cc9e531097` |
| `r13-mcp-live-check.py` | `9308abd8619f1e15b4a27f71074253056e69c1cb68374e3dcd820ec58ec05c5a` |

本轮未新增源码修复、远端推送、main 合并、模型安装、额外 scheduler 触发或 KB 自动合并。
沿用上轮 scoped 测试证据；只执行本轮发布件校验、候选验证和上述 live 检查，没有假称新跑全仓套件。

## 沉淀候选（Layer1，未直接入库）

- 类型：workflow / host-inconsistency；目标：在同一会话完成冻结发布，不靠删除账本或重启绕过。
- 触发与症状：命令显式指定 worktree，但 prepare-proposal 仍使用已有 session mapping，
  在较旧 main 中找不到 release input；文件本身并未缺失。
- 已确认根因：`ensure_workspace_contract` 优先选择 session contract。证据：源码读取、
  两工作区文件存在性对照、原生 handoff 后同一维护提案成功。证据状态 verified。
- 排除：补文件到 main、直接改 active JSON、把 CLI `--workspace` 当作已授权会话交接。
- 路由正例：维护卡根目录与 session lane 不同 → apply；必要条件匹配，来源 observed。
- 路由反例：相同 lane 内确实缺少发布源码 → skip；并非路由问题，来源 constructed。
- 执行合格例：官方原生交接后重新密封当前 worktree 输入 → pass；实际发布成功，来源 observed。
- 执行失败例：改 main/复制 receipt 强行通过 → fail；绕过身份边界，来源 constructed。
- 泛化会话、项目路径和版本后建议进入 anti-patterns；消费者为发布 runbook 和会话续接工具。
- 本轮使用 intent-guardian 保持原生批准与效果结算，plugin-creator 约束官方版本更新，
  kb-search 提醒将已生成 launcher 与真实安装态分开核验。
