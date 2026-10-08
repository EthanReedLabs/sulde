# Shell 参数路径误判修复（Codex 已安装；Claude 未完成；历史债务恢复独立待办）

> **当前状态（2026-09-27 终验轮）**
> - **Codex 已安装且 enforce 正例终验通过**：修复已集成 dev 并以正式事务安装到
>   **Codex 宿主**（代际 `0.2.5+codex.20260927061338-6d56455282:a5ff5ee2…`，
>   回滚目标保留）；协调者在真实交互 Codex 会话完成原生 Allow 后，同一调用
>   真实 Pre/Post 均为 **enforce / live_verified**，分类 **unknown**、
>   **allow / non_material_observation / verification=none**，原命令 12 项测试
>   通过、exit 0（详见"enforce 终验与精确清理条件"节末的终验补齐记录）。
> - **负例**：**已装 runtime 隔离入口验证**（PreToolUse 预拒绝 deploy，隔离
>   状态目录）；不是真实宿主负例，未升级。
> - **Claude 宿主未安装**（0.8.4 旧 runtime，缺口见"Claude 交接"节）。
> - **历史债务恢复独立待办**（3 条 attempt + 127 条历史，恢复能力缺口已登记）。
> - **线上业务试验（DMIT-Pro）独立待办**。
> - **资源清理**：任务 worktree/分支**仍待恢复**（本会话无 guardian 映射，
>   清理条件缺口已登记；前置持续满足）。
> - **双宿主重装（2026-09-27，用户授权）**：main 发布合并 `e7ea4f9`（0.8.5，
>   全量门禁 2457 项、4 失败分流处理）；Codex 新代际
>   `0.2.5+codex.20260927071122-de3a66fbaa:a5ff5ee2…`（内容与上一代一致，
>   上一代 retired alias 保留）；Claude 更新 **0.8.4 → 0.8.5**
>   （resources `974f6414…`，已装链探针 6/6 通过，0.8.4 目录保留可回滚，
>   重启后新会话生效）。证据
>   `~/.sulde/data/test-evidence/20260927T075338.199-8c0828a34f92.json`。
> 下文各"验收轮"小节为历史过程记录，按轮次保留。

## 范围与状态

- 用户目标：修复跨设备 ChatGPT 消息加载失败。此修复只处理阻止限时出口对照工具复测的本机保护误判，不是网络故障修复。
- 来源工作区：`/Users/eric/Freedom`；经原生确认的修订 r43。
- 分支：`task/fix-command-effect-20260926`，从 dev `9936c7b9e987100ba53f0e3e6af459fd59767ece` 建立。
- 只修改 resources.py、针对性测试及本报告。
- 交付身份（更正 2026-09-27 验收轮）：源码修复与回归测试已随本报告以提交
  `ab597d821b7e1d40328aa4d9a6c7abb2b5ee3dea` 记录在本分支（作者 eric.gao.tech，
  2026-09-27 12:07 +0800，父提交 9936c7b）。此前版本报告写"未提交"与事实不符，现予更正：
  提交、未合并 dev/main、未推送、未安装、未激活。
- 本轮验收（2026-09-27，发布前）新增：实际 Hook 链路验证（隔离状态目录）、
  候选发布件构建与验证、生产账本原误分类 attempt 只读定位。均未改变生产状态。
- 未改变线上机器、路由器、密钥、通知或历史审计。

## 根因与修复

`_command_effect` 在执行形状判断后，对整条命令匹配 `\bdeploy\b`。
因此 `python3 -B -m unittest discover -s vpn-deploy/personal-fleet/tests -p test_chatgpt_trial.py -v`
被标记 external_write；缺少外部效果核验器，继而产生错误的外部写入证据负担。

修复只收窄 deploy 分支：已有解析器证明单一可执行命令时，不把参数/路径里的 deploy 当成调用。
直接 deploy、绝对路径 deploy、可解析组合中的 deploy 仍为 external_write；不透明组合、环境赋值和包装器保留保守分类。
未知 Python/Node/测试脚本仍为 unknown，不因此获得只读证明。其他上传/HTTP 写入规则未改变。

## 可复核验证

以下命令均在独立 worktree 执行，退出码 0，共 53 项测试通过：

```text
python3 -B -m unittest discover -s tests -p test_intent_guardian_resources.py -v   # 17
python3 -B -m unittest discover -s tests -p test_intent_guardian.py -k command -v  # 9
python3 -B -m unittest discover -s tests -p 'test_command*.py' -v                 # 19
python3 -B -m unittest discover -s tests -p test_effect_router.py -v             # 8
git diff --check                                                              # 通过
```

新增 4 项参数化测试覆盖真实失败命令、路径和参数中的 deploy、真实部署、环境与权限包装器、管道、上传、HTTP 写入、危险组合及只读检索。
未运行全仓发布门禁。当前安装的 immutable runtime 仍是旧版；不能把这些测试解释成当前会话已恢复或 ChatGPT 已修复。

## 实际 Hook 链路验证（2026-09-27，隔离状态目录）

经真实入口 `hooks/pre_tool_use.py`（stdin JSON → `process_hook` → `normalize_hook_event`
→ `_command_effect` → policy），在一次性项目 + 一次性 `SULDE_HOME` 下验证。

**v1 探针（`ab597d8` 轮，保留为历史）**：deny/confirm 两档契约矩阵，误分类以 deny 可见。
缺陷：v1 以账本顶层字段取 effect（真实账本行是 `{schema, contract, decision, event}`
嵌套结构），取到空列表；且对静默放行只有间接证据（`material_sequence`）。
v1 结论方向正确，但证据强度低于 v2，以 v2 为准。

**v2 探针（本轮）**：按真实账本 schema 提取事件；对退出码、结构化 permission decision、
账本分类逐项断言，任何不符即非零退出；正例补齐 Pre → 实际执行 → Post 链
（夹具：`vpn-deploy/personal-fleet/tests/test_chatgpt_trial.py` 平凡通过测试 +
echo-only 未知脚本，均无外部副作用）；负例（deploy/scp/HTTP 写/rm -rf）只判定不执行。

| 用例 | 修复前基线（9936c7b resources.py） | 修复后（ab597d8/581194a） |
|---|---|---|
| C1 原失败命令：unittest `-s vpn-deploy/personal-fleet/tests` | **账本记 `external_write`**、Pre deny（`external_effect_not_authorized`）→ v3 守卫下不执行、不调 Post，`pending_at_pre` 为空（债不由 deny 路径产生） | **不 deny**；账本记 `effect=unknown`、`reason_code=non_material_observation`、`verification=none`；执行通过；无任何 external_write 债务 |
| C6 未知脚本（夹具 echo-only） | 不 deny，`unknown` | 不 deny，`unknown`（未被伪装成 read；非 material 观察即持久证明） |
| C2 真实 deploy / C3 scp / C4 HTTP 写 / C5 rm -rf | 结构化 deny | 结构化 deny（保持；判定验证，未执行） |

探针退出码（v3，deny/异常后不执行不调 Post）：修复树 **exit 0（6/6 断言通过）**；
候选 **exit 0**；基线对照 **exit 1（唯一失败 = C1 误拒绝断言，即误分类+误拒绝）**。

**债务归因更正（v3，以 v3 为准）**：v2 曾报告"基线现场产生 pending 验证债
`att-da1efd96…`"——那是 v2 守卫缺陷的产物：deny 后仍执行命令，Post 观察到一次
未被授权的真实执行，作为 pre-execution gap 记债（这本身恰是保护在正确工作）。
v3 修正后：基线 deny 路径**不**产生债务（`pending_at_pre=[]`）。生产账本中
两条真债（`32eb291b…`/`f33f97cf…`）的成因是不同路径：当时事件被**允许**
（reason_code=event_allowed、verification=required）后完成回调未获验证——
即"允许但未验证的 external_write 分类"才是生产债务来源；本修复使其不再发生。

结论：

1. C1 的误判→正确变化与本补丁一一对应（同链路同输入，仅 resources.py 回退即复现误判与误拒绝；v3 已证明 deny 路径不产生债务，生产真债来自"被允许但未验证"路径，见"债务归因更正"）。
2. 分类证据为账本阳性记录（`effect=unknown`），不再依赖"无 external_write 即正确"的空证据。
3. 隔离执行链（Pre→执行→Post）证明同命令真实执行完成后不产生 external_write 债务
   （无 open 事件、无 completed_calls 债务行、无 pending_verifications 行）。
4. 53 项源码测试按输入等价性复用（工作树自 `ab597d8` 起干净、相关文件未变）；官方定向
   计划（`test-evidence.py plan --base dev`）判 risk=small，定向集
   `test_intent_guardian` + `test_intent_guardian_resources` 均在已验输入内。

## 候选发布件验证（2026-09-27，本轮干净重建）

按仓库正式流程在新隔离目录重建候选，全程 `PYTHONDONTWRITEBYTECODE`/`python -B`；
源码树与候选运行前后快照核对（`docs/evidence/command-effect-path-repair-20260926/tree_snapshot.py`）：

- 源码树：运行前后快照逐字节一致（1788 files，`c0328c8e91ab0eff…`，字节码 0）。
- 构建：`python3 -B scripts/release/stage_plugin.py --target claude --output <新隔离目录>`
  → 828 files / 390 corpus documents。
- **候选身份（本轮有效）：`candidate_tree_sha256 = be4c698d8b1ed0b17fb14d8e7678722f67142df6cac8bebf142aeaec5d4adbd1`**
  （828 files，排序路径+内容 sha256，排除派生字节码）。
  上一轮身份 `dd9881b3…`（852 files）作废：其中含 24 个探针进程写入的 `__pycache__`
  字节码文件（见障碍记录）。
- 代码同一性：候选内 `resources.py` sha256 `974f6414482ab26f…` 与 `581194a` 工作树一致；
  4 个差异文件（HISTORY.json、install-agents.sh、stage_plugin.py、launchagent plist）
  均为 staging 归一化占位符替换，已抽查确认。
- 候选 Hook 链路：v2 探针 6 用例 exit 0；打包门禁：
  `SULDE_PLUGIN_UNDER_TEST=<候选> tests/p1_hook_dryrun.py` 20/20 exit 0；
  `test_stage_plugin*` 16 OK（1 skipped Windows）；`test_candidate_codex_plugin` 19 OK。
- 运行后候选快照：文件零漂移；p1 harness 进程曾向候选写入 94 个字节码文件
  （见障碍记录），清除后身份复核不变。
- 全量测试未跑：官方定向计划判 risk=small/targeted；共享链已由定向批次直接覆盖；
  全量留给合入前独立验收方。

## 生产账本原误分类 attempt 定位（只读，未修改）

契约：`interactive:e288edd841f377ca31564a3e`（workspace `/Users/eric/Freedom`，enforce，
revision 47）。账本：
`~/.sulde/data/kb/intent/workspaces/e288edd841f377ca31564a3e.active.events.jsonl` 及
同名 `.active.json` 的 `runtime.completed_calls`。

误分类 attempt（`effect=external_write`，`verification_kind=unsupported`，
`verification_sha256=""`，即外部写验证债），按证据强度分组：

**摘要匹配组（2 条，target 摘要与原失败命令 sha256 前缀逐字吻合，已独立重算验证）**：

| event_id | call_id | target | at (UTC) |
|---|---|---|---|
| `32eb291bea580d3631f884c7` | `exec-3d8f9662-d506-47ee-a2fa-fab7ca72010f` | `[command:734d771c7128caf3]` | 2026-09-26T03:08:26Z |
| `f33f97cf1b1f0826230822c7` | `exec-8c6d8574-5389-4d27-8a59-0b0e5a995565` | `[command:734d771c7128caf3]` | 2026-09-26T03:56:23Z |

**未确认组（1 条，不能证明与原命令相关）**：

| event_id | call_id | target | at (UTC) | 未确认原因 |
|---|---|---|---|---|
| `2c895253ab84617f51c6d0eb` | `exec-ee54216d-2109-4aee-899c-073ab8849662` | `[command:8cac7034d43d57c1]` | 2026-09-15T06:39:18Z | target 与 arguments_digest 均无法与已知命令比对（摘要不可逆），仅同属 Bash external_write+unsupported 形状 |

同一命令另有 3 条拒绝重试记录（event_id `4ab4900aa4975ea004429659`、
`e9b5ba15937a67102f8b71df`、`5eeca788f8df6311e591129e`，reason_code=policy_evaluation，
即"复测被阻断"的直接证据）。

### 历史债务恢复：现有接口能力核查（只读）与恢复缺口

对既有接口的只读核查结论：

1. `scripts/kb/correction_intervention.py`：纯控制面事件日志/投影（自由文本与会话标识
   只以单向摘要入库）。其 `applied` 仅表示"已送达安全宿主边界或中断受管运行"，
   **不触碰、不结算、不重分类**契约 runtime 的 `pending_verifications`/`completed_calls`。
   ——上一轮报告把它列为"更正方式"属于恢复接口误用，现予撤回。
2. "新事件自然更正旧债"不成立：账本与 runtime 列表按 event_id/call_id 记账，
   新命令产生新事件，旧 attempt 行保持原状，不会被新分类消除。同样撤回。
3. `intent_guardian_parts/historical_retirement.py`：只针对冻结历史契约纪元
   （relocation blocker 投影），且显式拒绝 external 效果
   （"external or linked effect must use effect recovery"）；
   `completed_calls` 在其 TELEMETRY 集内被视为非 material 观察。
4. `intent_guardian_parts/recovery.py::_reconcile_read_only_effect_debt_locked`：
   现存唯一的消债接口，**仅限 `effect == "read"` 的遗留干预**；
   对 external_write 误分类→unknown 的重分类无任何入口。
5. 投影消费者：`sulde_projection/models.py` 将 `pending_verifications` 计入投影，
   `event_observer`/`production_recovery`/`operational_readiness`/`terminal_invariants`/
   `self-repair`/`organ-evolution` 均消费这些 runtime 列表——任何更正都必须同步这些投影，
   现有接口没有能同时满足"精确更正 + 投影一致"的入口。

**恢复缺口（独立登记，本轮不新增接口）**：现有接口不支持"精确 Bash 分类更正及其
投影消费者同步"。按本轮边界，不自行新增通用消债接口。3 条 attempt（含未确认 1 条）
保持原状，留待独立恢复任务按上述缺口设计专门方案；127 条历史记录不动，生产账本不变。

## 安装后原命令复测步骤（本轮不执行）

1. 前置：候选经独立验收、按正式事务安装路径激活（新 runtime generation 可从事件
   `artifact_generation`/`loaded_module_generation` 字段核对）。
2. 在 `/Users/eric/Freedom` 正常保护（enforce 契约、不改权限）下原样重跑上述 unittest 命令。
3. 预期：不再出现 external_write 判定/拒绝；命令以 unknown-material 记账并实际执行。
4. 对照实验边界（需单独原生确认后才执行）：仅 DMIT-Pro、600 秒自动恢复、
   真实用户请求前后比较，禁止自动推广。

## 执行障碍记录

**ab597d8 轮（上一轮）**：

1. 字节码污染（实际发生）：探针进程未禁字节码，import 源码树时在 worktree 写入
   `scripts/kb/__pycache__` 等 4 处（git-ignored 未进提交，已清理）；
   旧候选快照身份 `dd9881b3…`（852 files）含 24 个 `__pycache__` 字节码文件，
   该身份作废，由本轮干净身份替代。
2. 探针取字段错误（实际发生）：v1 从账本行顶层取 `effect`，而真实 schema 是
   `{schema, contract, decision, event}` 嵌套，取到空列表；v1 仅靠间接证据
   （`material_sequence`、deny 出口）支撑结论。v2 已按真实 schema 提取并加断言。
3. Hook 对允许类决策静默，链路分类不可直接观察：改用 enforce 契约使误分类在出口可见
   （方法成本，非产品缺陷）。额外耗时/Token：无计量数据，unknown。
4. 账本不存命令原文（仅 `arguments_digest`），定位原 attempt 需重算摘要比对。
   额外耗时：unknown。
5. 无实际误拦截、绕行或重复测试；等待主要为本轮只读检索账本（2623 个 workspace 文件）
   的 grep 时间。

**581194a 后本轮**：

6. 恢复接口误用（实际发生，报告层面）：上一轮把 `correction_intervention.py` 列为
   "更正方式"、并把"新事件自然更正"列为可选项；只读核查后确认两者均不成立，
   已撤回并改列为恢复缺口（见"历史债务恢复"节）。生产账本未因此发生任何写操作。
7. 字节码污染（实际发生，当场捕获）：p1 dryrun harness 进程 import 候选树时向候选写入
   94 个 `__pycache__` 文件；运行后快照对比捕获，清除后候选身份复核不变
   （`be4c698d…`）。探针 v2 自身全程零字节码（`PYTHONDONTWRITEBYTECODE` + `python -B`）。
8. transcript 误删（实际发生）：构建新隔离候选时 `rm -rf` 波及同目录下已生成的
   v2-fixed/v2-base transcript，重跑探针再生（夹具确定性，结论一致）。
9. 断言误设（实际发生）：v2 初版要求"Post 必须结算 completed_calls"，但非 material
   事件（unknown/non_material_observation）本就不建 open 事件；改为断言账本阳性分类。
   该误设使探针首次运行即非零退出，按设计工作。
10. 债务归因错误（实际发生，已更正）：v2 基线运行在 deny 后仍执行并调 Post，由此产生
    的 `att-da1efd96…` pending 债被误归因为"误分类路径的债务"；实为 Post 对未授权执行
    的 gap 记账（保护正确工作）。v3 守卫修正后基线 deny 路径不产生债务；生产真债来源
    更正为"被允许但未验证的 external_write 分类"（见"债务归因更正"）。

## 后续边界

1. 当前源码分支未进入正式发布。安装/激活属于本次 r43 明确排除的后续动作，需要单独可读范围和原生确认。
2. 安装应沿仓库正式校验及事务安装路径，禁止直接改缓存或 launcher。确认运行时代际及必要的宿主恢复步骤。
3. 原有误分类 attempt 不会因源码修复自动消失。只允许有证据、追加式的更正或受控恢复，不删除审计、不伪造成功、不一批清掉未知旧操作。
4. 被阻断的 ChatGPT 试验最新版测试仍未完成；后续需在正常保护下原命令复测，并重新声明线上试验范围。仅 DMIT-Pro，600 秒自动恢复，真实用户请求前后比较，禁止自动推广。


## 集成发布与安装验收（2026-09-27 第三轮）

**集成**：`task/fix-command-effect-20260926` @ `1e09129`（含 v3 探针守卫与债务归因更正）
按 CONTRIBUTING 规则 no-ff 合入 dev → **dev `d36b37b`**（不夹带其他候选，未动 main）。
集成差异 = 本任务 4 个提交，无冲突、无共享链漂移，既有等价证据全部复用；
定向门禁（probe v3 / p1 20/20 / resources 测试）在集成树上重跑通过。
cachebuster 刷新 `85c3107`（`0.2.5+codex.20260927061338-6d56455282`）。

**安装（仅 Codex 链；宿主原生确认后执行）**：

- 候选：`20260927T061352Z-b2fb304ce89b`（prepare→verify→promote 正式流程；
  首次 promote 因同版本不同内容被版本碰撞拦截，刷新 cachebuster 后重走）。
- 代际：`0.2.5+codex.20260927061338-6d56455282:a5ff5ee25141d7678a28869f7a87840d9630688ab13f663ed06c50d8c671a90c`。
- 事务：`f37e568cb2034381be65f5b0600bd004`；`generation_verified`，
  `scheduler_ready_live_host_unverified`（live 部分由下述真实宿主验收补足）；
  `restart_required=true`（已以全新 codex 会话验收）。
- 回滚目标：原部署 `0.2.5+codex.20260923135758-a1d7cd1c4c:cc7bbfa9…` 经 controlled
  retired alias 保留（`retired/sulde-local/sulde/0.2.5-codex.20260923135758-a1d7cd1c4c-479f82f2…`），
  事务日志可回退。
- 身份链：集成树 `85c3107` = 候选工件 = 已装 runtime 的 resources.py
  sha256 `974f6414482ab26f…`（含修复标记）逐环一致。

**真实宿主验收（Codex 0.155.1，实际会话；范围=**shadow 会话合同**，见下节 enforce 终验状态）**：

- 正例（/Users/eric/Freedom，生产环境）：原命令
  `python3 -B -m unittest discover -s vpn-deploy/personal-fleet/tests -p test_chatgpt_trial.py -v`
  → **12 项测试全过，exit 0**；新会话账本记录 `effect=unknown`、
  `non_material_observation`、allow、`verification=none`；
  会话契约 `pending_verifications=[]`、`pre_execution_gaps=[]`、
  metrics `allowed=2 denied=0`。**新调用不再因参数路径含 deploy 而误判或产生债务。**
- 负例（隔离状态目录）：`deploy --env production --config fleet.yaml` 经已装 runtime
  PreToolUse hook **预拒绝**（"此动作需要一次当前会话确认"），命令未执行。

**Freedom 业务与历史边界**：

- 复测前核对：测试文件为纯单元测试（subprocess 全程 mock，12 项，无真实网络/外部副作用）。
- 旧债务未动：workspace 契约（`e288edd841f…` rev 47）中摘要匹配 2 条
  （`32eb291b…`/`f33f97cf…`）、未确认 1 条（`2c895253…`）、其余 127 条历史条目
  与 pending 行 `att-cb481f30a76976cde0ce90f5` 全部原样。
- 旧 pending 债务未阻断新会话（新 task_epoch/新会话独立记账）；
  本次复测通过 = 安装验收通过 + 该命令的业务复测通过；ChatGPT 业务功能本身
  （跨设备消息加载）仍属后续限时出口对照试验范围，未执行 DMIT-Pro 线上试验。

**Claude 侧安装（本轮原生确认为"Codex + Claude 两侧"）——受阻，如实登记**：

Claude 插件 `sulde-cc@sulde` 仍为 0.8.4（旧 resources.py `d2b526b8…`）。
机制性障碍：其市场源为目录市场，指向 `/Users/eric/ClaudePlugin/sulde-pro`
（main checkout，本轮禁止修改）；产品版本同为 0.8.4，更新需产品版本变更
（release 提交，属 main）或市场源重指（全局宿主配置变更）。
两者均超本轮边界，按"范围外问题只登记"处理，不强改配置。
影响：Claude 宿主上的 guardian 仍为旧分类器；受影响会话（provider=codex）不受此影响。

## 状态与合入/安装顺序（2026-09-27 第二验收轮收尾；**历史记录**，状态已被第三轮取代）

**当时状态：`candidate-awaiting-independent-review`。** 该轮未自行 accepted；
当时未合并 dev/main、未推送、未正式安装、未执行线上试验、未修改生产账本。
（后续第三轮已完成集成与 Codex 安装，见"集成发布与安装验收"；本节保留为历史。）

当时证据分层结论（历史快照；"基线对照现场捕债"表述已被 v3 归因更正取代）：

| 层 | 第二轮时状态 |
|---|---|
| 源码分类修复（executable/argument 区分） | **已证**（53 项源码测试 + v2 探针双向对照） |
| 隔离执行链（Pre→执行→Post 不产生 external_write 债务） | **已证**（v2 探针夹具链） |
| 候选发布件（`be4c698d…`）加载补丁且链路有效 | **已证**（代码同一性 + 候选探针 exit 0 + 打包门禁） |
| 生产安装与验收 | 当时未验收（第三轮已完成 Codex 安装与真实宿主验收） |
| 历史债务恢复（3 条 attempt + 127 条历史） | **尚缺能力**（现有接口不支持精确 Bash 分类更正及投影同步；已登记为独立恢复缺口） |

候选身份：分支 `task/fix-command-effect-20260926`，验收基线 `ab597d8` + 本轮提交；
候选发布件 tree sha256 `be4c698d8b1ed0b17fb14d8e7678722f67142df6cac8bebf142aeaec5d4adbd1`。
证据：`docs/evidence/command-effect-path-repair-20260926/`（探针 v2、快照工具、
transcript）与宿主数据目录
`~/.sulde/data/test-evidence/20260927T044926.641-6e9c4d2cc010.{json,log}`。

剩余阻塞：独立验收方复核；历史债务恢复缺口需独立任务立项；线上对照试验需单独原生确认。

建议合入/安装顺序：
1. 独立验收通过 → 合入 dev（fast-forward 或按仓库合并规约）。
2. dev 发布门禁（含全量批次，由验收方执行）→ 沿正式事务安装路径安装激活候选
   `be4c698d…`，核对运行时代际。
3. 安装后按"安装后原命令复测步骤"复测原 unittest 命令。
4. 历史债务：独立恢复任务按"恢复缺口"节设计方案（含投影消费者同步），
   摘要匹配 2 条与未确认 1 条分开处理；127 条历史记录不动。
5. 最后才进入线上对照试验（单独授权）。


## enforce 终验与精确清理条件（2026-09-27 第四轮；**历史记录**——enforce 终验已由
## 协调端真实交互会话证据补齐，见本节末"终验补齐（第五轮）"，本节过程保留）

**当时状态：enforce 终验未完成——被保护设计阻断，非缺陷；未绕过。**

按正常授权流程执行（无手改合同、未切 shadow、未放宽策略）：

1. 专用验收工作区 `/tmp/ce-enforce-accept/proj`（Freedom 测试树副本，12 项测试
   纯单元、subprocess 全 mock，执行前复核无外部副作用；chatgpt_trial 的 urllib 块
   仅 localhost 且不被测试触达）。
2. `create`（显式合同，enforce）→ 复核 activate 语义后改用 `create-from-brief`
   （已批准 L3 简报的设计入口）→ `activate`：合同
   `d937b43a81f3734be3d9860a.active.json`，mode=enforce、confirmed_by=human、
   external_write=confirm、destructive=deny、allowed_paths=验收工作区。
   Freedom 现役合同未被触碰（activate 会覆盖 workspace 合同，故不用 Freedom）。
3. 以启动提示 `SULDE_INTENT_CONTRACT` 运行已安装 Codex runtime（codex exec）
   两次，均被 **`TASK_REVIEW_REQUIRED`** 闸门拦截：enforce 首任务 lane 要求
   原生 Allow/Deny 卡，而 codex exec 的 `never` 审批策略无法呈现
   （stdout 原文："Command not run"——闸门正确工作，命令未执行）。
4. 决策面核查：`agent-decide-proposal` 正确不可用（提案文本命中外部写入边界词，
   agent_eligible=false，selected_route=human）；`native-decision` 决策面明示
   "本宿主无已验证原生决策面……do not ask the user to type a phrase, copy a
   digest, or run a CLI command"；本会话的自批尝试被宿主权限层拦截（正确）。

**精确缺口**：enforce 首任务人审卡只能在**真实交互 codex 会话**中呈现与决定；
codex exec（非交互、never 策略）与本会话宿主均无已验证原生决策面。
**恢复路径（已保留）**：验收工作区、合同 `d937b43a…`、pending 提案
`b47a9845…` 原样保留；下一个真实交互 codex 会话进入该工作区即会原生呈现
卡片，批准后按本报告"真实宿主验收"同法复验并归档。
证据：`~/.sulde/data/test-evidence/20260927T065046.239-31158705a6ca.{json,log}`
（两次 gate stdout/stderr 原文、决策卡全文、合同身份、gated 会话
`01a0e19c-85ed-7d60-ad35-bdab62940dbe`）。

### 终验补齐（第五轮，2026-09-27：协调端真实交互会话完成 enforce 正例终验）

协调者在现有交互 Codex 会话内经原生 Allow（授权回执
`4e58919c4c6f34ff0d0888446748a69a13179befab109491df9055d75e13da52`，
合同 revision 18→19）完成上节被阻的终验。**本会话不将该回执用作自身权限。**
本仓库回读核验全部通过：

- **命令与结果**：原命令（target 摘要 `[command:734d771c7128caf3]`，与命令
  sha256 前缀独立重算吻合）仅运行一次：**12 tests, 0.030s, OK, exit 0**。
- **真实 Pre/Post 同一调用**：event_id `dc4516378626188d8de58343`、
  call_id `exec-4eef1082-c7c8-4c29-971a-a6e9215cca0d`，两条记录均为
  **mode=enforce / supervision_status=live_verified / effect=unknown /
  allow / non_material_observation / verification=none**。
- **代际身份**：两条记录 `loaded_module_generation`（`4f723803…`）与
  `artifact_generation`（`0.2.5+codex.20260927061338-6d56455282:a5ff5ee2…`）
  分别各自前后一致；两字段是不同身份，不要求互等；artifact 代际与已装
  runtime 安装代际一致，resources.py `974f6414…` 与源码修复一致。
- **合同洁净**：快照 pending_verifications=0、pre_execution_gaps=0、
  open_events=0、integrity_breaches=0（enforce active rev 19，
  intent `completion:658277a0f9d2c235958cad16`）。
- **适用范围**：本次为有界 enforce 正例终验（当前交互宿主），不是 Sulde 全部
  能力验收；负例仍为"已装 runtime 隔离入口验证"，未升级为真实宿主负例；
  工具输出为 exec 合并流，未分别归档 stdout/stderr（证据内已声明）。
- **证据位置**：`/Volumes/Optimus/Sulde/tasks/command-effect-enforce-acceptance-20260927/`
  （`REPORT.md` + `evidence.json`，schema
  `sulde-command-effect-live-enforce-acceptance-v1`；Optimus 为外部挂载卷，
  挂载不可用时以本节摘要与事件身份为准）。审批后宿主提示保存了命令 prefix
  而调用未提供 prefix_rule：该保存行为仅登记待独立审计，本轮不复用、
  不作为未来权限。
正例负例证据复用声明：shadow 正例（上轮 Freedom 实测）与已装 Hook 隔离负例
按输入等价性继续有效，未重跑。

**资源清理条件（只读核查结论；资源保留）**：

- 本会话在生产 guardian 侧**无 session mapping**（生产仅一条 2026-09-20 的
  claude 映射；sulde-pro 仓库无活跃合同），本会话宿主 hooks 由旧 0.8.4
  runtime 承载，不产生映射。
- 现有正式入口均不能合法为无映射会话建立绑定：`release-completed-workspace`
  要求当前会话映射（fail-closed 已实测一次，未反复调用）；
  `prepare-task-continuation`/`prepare-workspace-handoff` 面向既有源合同与
  原生卡；`rebind-workspace` 面向孤儿合同迁移。均非"为无映射会话自建绑定"。
- 绑定只能由真实 hook 流（被监督宿主内的 user_prompt_submit）自然建立。
  因此任务 worktree `.worktrees/fix-command-effect-20260926` 与分支
  `task/fix-command-effect-20260926` **保留待恢复**：由任一在生产 guardian
  有映射的会话（或被监督宿主内的新会话）执行
  release-completed-workspace → git worktree remove + branch -d →
  finalize-workspace-cleanup 即可，前置（已合并祖先、树干净）持续满足。
  不顺手开发恢复机制。

## Claude 交接（安装缺口，后续任务输入；本轮未改任何配置）

- **缺口**：Claude 插件 `sulde-cc@sulde` = 0.8.4（2026-09-20 安装，resources.py
  `d2b526b8…` 旧分类器）；本修复只在 Codex 侧生效。受影响会话（provider=codex）
  不受此缺口影响，但 Claude 宿主上的同类 Bash 仍会被旧分类器误判。
- **现有安装来源**：marketplace `sulde` = **directory 源**，指向
  `/Users/eric/ClaudePlugin/sulde-pro`（main checkout）；插件经
  `~/.claude/plugins/cache/sulde/sulde-cc/0.8.4` 装载，版本取自
  `.claude-plugin/plugin.json` 的 product version。
- **可用正式发布入口**：仓库既有发布流程本身（dev 开发、验证、
  release 提交按规约合入 main → 目录市场随 main checkout 更新 →
  `claude plugin` CLI 更新插件）。**不认定"升版必须直接改 main"**——
  升版提交在 dev 完成并验证，main 只接收按 AGENTS.md 规约的发布合并。
- **最小变更方案**：① dev 上对 `.claude-plugin/plugin.json` 做产品版本升版
  （0.8.4 → 0.8.5，或按仓库版本规约）+ 必要的 codex cachebuster 已在 `85c3107`
  完成；② dev 发布门禁通过后按规约合并 main；③ `claude plugin update sulde-cc@sulde`
  （或等价 CLI 流程）装载新代际；④ 以本报告"真实宿主验收"同样的正负例
  在 Claude 宿主复验。
- **回滚方式**：Claude 插件缓存按版本目录存放（`0.8.4` 目录不会被升版删除），
  回滚 = CLI 重装/指回 0.8.4；不涉及账本或 Codex 代际。

## 推送边界（本轮不 push；下表为 dev 相对 origin/dev 的全部待推送提交）

origin/dev = `51bb927`；本地 dev 待推送提交（时间序，含此前知识库提交）：

| # | commit | 归属 | 内容 |
|---|---|---|---|
| 1 | `18e1875` | 知识库（本轮任务前） | verified Docker export / WeChat payment guidance |
| 2 | `9936c7b` | 知识库（本轮任务前） | merge: curate Docker export and WeChat payment knowledge |
| 3 | `ab597d8` | 本任务 | command-effect deploy 分支收窄（源码修复+回归） |
| 4 | `581194a` | 本任务 | 第一验收轮报告与证据 |
| 5 | `9cd683a` | 本任务 | 第二验收轮：干净候选、v2 探针、恢复缺口 |
| 6 | `1e09129` | 本任务 | v3 探针守卫 + 债务归因更正 |
| 7 | `d36b37b` | 本任务 | merge: 集成进 dev |
| 8 | `85c3107` | 本任务 | codex cachebuster 刷新 |
| 9 | `e0b8187` | 本任务 | 集成/安装/验收记录 |
| 10 | 收尾轮 docs(release) 提交 | 本任务 | 报告现状校正、Claude 交接、推送边界与收尾记录 |

未获明确推送授权前不执行 `git push`。

## 任务资源收尾记录（2026-09-27 收尾轮）

- 前置已满足：任务分支 HEAD `1e09129` 是 dev 祖先；任务 worktree 干净（0 改动）。
- 释放流程按规约调用 `release-completed-workspace`，**按设计 fail-closed**：
  本会话在生产 guardian 侧无当前 session mapping（生产仅有 2026-09-20 一条
  claude 映射；sulde-pro 仓库无活跃契约），流程拒绝创建完成锚点。
  按纪律不绕过审计链直接删工作树/分支。
- 现状：worktree `.worktrees/fix-command-effect-20260926` 与分支
  `task/fix-command-effect-20260926` 保留待清；后续由绑定 dev 契约的会话执行
  三步流程（release-completed-workspace → git worktree remove + branch -d →
  finalize-workspace-cleanup）即可完成，所有前置已就绪。

## 沉淀候选（Layer1，未写入全局知识库）

- 问题类型：bug-fix / workflow。
- 用户真实预期：快速恢复 ChatGPT，不能为恢复测试而削弱保护。
- 触发场景：未识别本地脚本参数路径含 deploy；全命令关键词匹配产生错误效果类别。
- 可观察症状：本地 unittest 被登记 external_write/unsupported，后续复测被未知效果阻断。
- 已确认根因：效果分类器把参数数据当执行行为。历史记录完整生命周期是否还有独立缺陷：inconclusive。
- 证据状态：源码根因、收窄回归、隔离执行链（Pre→执行→Post 不产生误债）及候选发布件链路 verified；安装生效、业务修复 inconclusive；历史债务恢复确认尚缺能力（现有接口不支持精确 Bash 分类更正及投影同步）。
- 已排除假设：命令含 deploy 字符串不足以证明发生部署；不能将未知执行结果视为外部写入事实。
- 一手证据：上述源码 diff 与 53 项本地测试；Freedom 的 `chatgpt-trial-20260926.md`。
- 正确做法：先按可执行形状区分代码与数据；无法证明的脚本保留 unknown；历史更正必须追加。

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | unittest 的 vpn-deploy 参数路径触发外部写入债务 | apply | 字符串被误作执行动作 | observed |
| 路由反例 | scp 上传后缺少回调 | skip | 真实外部动作不能按路径误判消债 | constructed |
| 执行合格例 | 测试命令归 unknown，真实 deploy/scp 保持 external_write | pass | 收窄误报但不把未知执行放行为只读 | observed（回归测试） |
| 执行失败例 | 所有 unittest 一律 read 或直接删除旧 attempt | fail | 测试可产生副作用，审计不能被抹除 | constructed |

- 上浮时删除/泛化：本机路径、分支、用户业务与会话标识。
- 可复用内核：命令效果判断区分 executable 与 argument；分类证据与完成证据分离。
- 建议容器：anti-patterns；与现有 0242 先判重，不直接入库。
- 候选消费者：Hook/命令效果分类器、回归测试及审计恢复检查表。
