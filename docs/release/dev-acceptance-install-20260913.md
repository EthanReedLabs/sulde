# DVA 正式安装与 live 验收

日期：2026-09-13。状态：**新候选已正式安装，当前会话 live 验收通过，已合 dev，证据已归档。**

前两次受阻均完整保留。下文「原始冻结范围」至「首次停止」是当时的证据，不代表最终状态；
后续 revision 4/5 经当前会话原生批准，只调整候选/解释器，不修改运行代码。

## 原始冻结范围

- 基线 dev：`21e4cc09513304366672305412c1938f65f002db`。
- 已验收源码：`ca1911592c035f4f022f51a8f24d2d0157c169d5`；至 dev 仅报告变化。
- 前置证据：[DVA 修复验收](dev-acceptance-fixes-20260913.md)：2198 total、2171 passed、27 skipped，无失败。
- 本轮只更新 Codex manifest cachebuster，使用官方 candidate prepare/verify/promote 链一次，
  收集安装后真实入口、当前 lane doctor、fresh MCP 与真实 Hook 负向证据。
- 允许官方安装器按既有定义重载原 16 labels，保留原 RunAtLoad；不额外启动后台业务或模型调用。
- 不新增源码修复、不手改生产缓存/账本、不清理全局历史债务、不推送、不合 main。
- 通过后只合入 dev，归档本轮证据，并通过官方完成释放清理本轮 worktree/分支。

## 执行顺序与停止线

1. 安装卡同时声明 local_write/external_write，密封 helper、未来版本、树摘要与安装器身份。
2. helper 一次、manifest validator、提交仅版本字段；不得在密封后修改运行源码。
3. candidate prepare → verify → promote；任何一步失败停止，不重复消费授权。
4. 独立效果核验，安装身份核对，系统 Python 只读状态、doctor、fresh stdio MCP、真实负向 canary。
5. 区分当前 lane ready 与全局历史 degraded；静态/模拟结果不得充作 live 证据。
6. 若必须新增修复或扩大权限，保留证据并请求新决定，不自动延长工作流。

## 前置检查

- dev 干净；main 用户的 `.ua` 三个文件修改及 `.sulde/` 保留。
- 当前已安装：`0.2.5+codex.20260913045930-43f6e3c807`，generation_verified。
- 旧 runtime tree：`c2a22c0cf060609832310cb679faa4d95ba870ca3eebc704ec8ff4abf159932a`。
- 官方 marketplace helper 返回 `sulde-local`；CLI 列表确认来源为现有本地 artifact。
- 安装解释器：既有 KB venv Python 3.10.7，PyYAML 6.0.3；不新增依赖。
- 准备 revision 2 receipt：`bb2f646e1eac454c202b3df14f3d96ee4c474f877da88585cea9b8a075b2c9d5`。
- worktree handoff receipt：`1b3075e5dae5b4dd26da61c921301bf27ace4a27c6be7788f86d3b54e221c4b4`。

## 本轮遇到的问题

- 将 skill-start 与 KB search 放入一个组合命令，Guardian 在执行前拒绝组合第 3 步；
  整组未执行。按各自独立命令登记/检索成功，无绕过、无生产效果。
- Agent 首次 preview 误用 `allow`，CLI 要求语义值 `approve`；只读预览拒绝后纠正，
  未产生裁决、回执或重复执行。

## 沉淀候选

采用 ap-0235 约束实际安装入口验证、ap-0252 约束解释器前置检查；原文已全文回读。
不写共享知识库。

### Layer1：一次性发布验证遇到执行环境拒绝

- **问题类型**：workflow。
- **任务目标/用户预期**：安装已验收修复，保持冻结范围，提供真实 live 验收。
- **触发场景**：macOS 受限沙箱内运行官方隔离候选验证。
- **症状**：验证返回 `[Errno 1] Operation not permitted`；按宿主要求原生提权重试同一
  命令后返回 `only a prepared candidate can be verified`。
- **已确认根因**：第二次不能验证是候选已进入 verification_failed，状态机只接受 prepared；
  第一次 EPERM 的具体系统调用没有被持久化，根因仍为 **inconclusive**，不断言源码回归。
- **已排除**：不是生产安装失败，promote 没有运行；当前 lane 无未决授权、无效果债务或 Hook 故障。
- **证据状态**：终态与生产未改变 verified；第一次错误调用点 inconclusive。
- **一手证据**：下方候选 state 与退出码；verify 源码异常分支只保存 str(error)，没有 traceback。
- **正确做法及验证**：保留失败候选，不改状态、不产生通过回执；新候选必须新决定。

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 一次性候选验证 EPERM 后无法提权重试同一候选 | apply | 环境失败已经落为终态 | observed |
| 路由反例 | 普通只读 Git 检查失败，未创建候选状态 | skip | 不存在一次性验证状态机 | constructed |
| 执行合格例 | 保留旧失败证据，经新决定创建同源码候选，在明确权限环境验证 | pass | 不篡改历史、不扩大源码范围 | constructed |
| 执行失败例 | 手改 verification_failed 为 prepared，或跳过 verify 直接安装 | fail | 绕过不可变证据与发布门禁 | constructed |

- **上浮边界**：泛化项目、机器路径、版本和提交；内核是一次性状态机的环境前置检查与
  失败后新候选流程；建议 work-model，消费者是发布清单与候选执行器；尚未修复，不标完成。

## 首次执行结果（历史）

- 正式 revision 3 receipt：`2a80284ce0f0942978200665d51454149534d74c750ecc9289dd7ac2f8d1d61c`。
- helper 执行一次；独立 content verifier 通过，attempt `att-a687c1994f14228910fcbc1f`。
- manifest 版本提交：`147c1edde5b2c5ba1b7aef17acac4a8d682ba9c1`，仅一行版本变化。
- 新版本 **仅在候选中**：`0.2.5+codex.20260913092700-3918bd5f72`。
- plugin validator：首次 Agent 错用 PATH Python（缺 yaml）exit 1；改用前置核验的既有
  Python 3.10.7/PyYAML 6.0.3 后 exit 0。没有安装依赖。这是本轮 Agent 执行不一致，
  不归咎于 DVA 修复。版本提交先于成功 validator 完成；prepare 在成功验证之后才执行。
- Git 写 index 首次被文件系统沙箱拒绝；原生提权后提交成功，不修改保护目录权限。
- candidate prepare：exit 0，1.296 秒，`dva-20260913`。
- candidate verify：exit 1，`[Errno 1] Operation not permitted`，
  2026-09-13T09:37:31.728547 UTC 记录 verification_failed。
- 按宿主沙箱重试规则申请原生提权，第二次命令 exit 1，状态门在进入验证前拒绝。
  不能把这两次调用写成“验证只调用一次”；验证主体仅首次进入，第二次未重跑。
- **promote 未调用，receipt_sha256=null，promotion_consumed=false**。
- state 的 live_prestate == live_poststate，live_preserved=true；涵盖 marketplace、插件、
  deployment、launcher、scheduler owner 身份，未改变生产 generation。

候选原始证据保留在本 worktree 的
`.sulde/public-export/dev-acceptance-install-20260913/candidates/dva-20260913/`。

| 项目 | 身份 |
|---|---|
| Source tree | `4882f78fb37c02c60ea947210bca235399840713` |
| Candidate runtime tree | `bf35a979ae4cb72fbf0cc4ab264d23a893ff85f68cc2e70b984ace8106f43945` |
| Candidate plugin tree | `0bcaf202513e5947fd0b44d8af6c5dc5de28912c6548546ac3e4f5f55b97f013` |
| state.json 文件 SHA-256 | `3cc4e73d2249a39108f5e3c7c2ec1c25848a9f86cbfdb011444c25df28addf0b` |

安装授权没有消费，只有 helper 的一次 continuation use。停止后只读 doctor 显示：
当前会话 operational ready，pairing settled，unsettled=0，cas_mismatch=0，effect debt clear，
Hook failures clear；**旧生产版本** scheduler 16/16 ready。这不是新版本的 live 验收。

## 首次停止（历史）

本次未完成发布，不合 dev/main、不 push、不清理失败 worktree，不要求用户重启会话。
建议保留同一运行源码与已生成版本，不重复 helper；批准一个新隔离候选，并在明确宿主权限
下重新验证，再按新卡执行一次 promote/live 验收。先检查是否能复用已有受支持候选入口；
若仍失败并确需代码修改，另行给出最小修复决定，不自动扩成架构任务。

## 续行控制与结果

用户确认保留旧证据继续，原生 revision 4 receipt：
`3cf35096be42d5d4f0ff558ddb85a57c8965f9af64397ec79d840cb6a77515ea`。
新候选 `dva-host-20260913` 在宿主权限 verify 通过（17.193 秒），没有再现 EPERM；
但 promote 被 PreToolUse 在执行前拒绝，候选保持 verified / promotion_consumed=false。
此时没有安装或重试外部效果。

只读定位：`resource_preflight.py` 的 `resolved_executable` 对 venv 路径执行 resolve；
`codex_candidate_promotion_candidate` 随后将其与 receipt.python.executable 做字符串比较。
而 `python_environment.inspect_python` 明确保留 venv 调用路径，避免改变 sys.prefix。
因此已验证的 venv 候选无法通过这条 promotion 入口。不能只比较 binary hash 就声称
不同环境等价，也不能手改回执。这个实现不一致已确认，**本轮未修源码**。

上次 R14 成功安装使用实际 Python 路径；本轮读取该环境确认版本为 3.10.7、PyYAML 6.0.3，
binary 与依赖内容摘要与 venv 一致，官方 `same_runtime` 返回 true。经新的原生卡明确
选择该环境，revision 5 receipt：`3b80da855b907e58590cfc11cfbdcf0ba6e5b14d0f53baa0e2f4737cd6545ddd`。
全程使用 `/Users/eric/.pyenv/versions/3.10.7/bin/python3.10` 重新 prepare/verify/promote，
未安装依赖、未重复 helper、未消费前一候选回执。

| 候选 | 最终状态 | prepare / verify / promote | 生产效果 |
|---|---|---|---|
| dva-20260913 | verification_failed | 1.296 秒 / EPERM / 未调用 | 无 |
| dva-host-20260913 | verified，未 promoted | 1.053 / 17.193 秒 / PreToolUse 拒绝执行 | 无 |
| dva-canonical-20260913 | promoted | 1.044 / 17.345 / 37.414 秒 | 一次安装，独立核验通过 |

三个候选的 runtime/plugin tree 均相同。最终候选基于
`12449578b16218ee2415276e70e30f8840dc850d`（Git tree `d4234529cdd16e86bb1436d9c0dd28552c4b374f`）；
与首个候选提交之间只有报告变化。版本仍为 `0.2.5+codex.20260913092700-3918bd5f72`。
canonical verification receipt：`46d5cb9600fd88c625d341e9c34fea08bd5e7ca87440760fca536ba2f15fc973`。
安装内部用时 37.306 秒，generation_verified，promotion_consumed=true，promotion_error=null。
安装 grant `0422b5b97e9e7d2d1c9b313c20b70a82297ea9540418e06418a014dd61cf9777` 消费一次；
attempt `att-8711f4d13e3cabc575413acb` 经 `codex_plugin_install_verify` 独立验证，
事件 `3f358cd6763be3f379aeb2c5`，2026-09-13T09:48:23.181013 UTC。

## 安装后 live 验收

- 新 installed cache 与官方 artifact 递归逐文件比较一致，exit 0。
- installed runtime tree：`bf35a979ae4cb72fbf0cc4ab264d23a893ff85f68cc2e70b984ace8106f43945`；
  plugin tree：`0bcaf202513e5947fd0b44d8af6c5dc5de28912c6548546ac3e4f5f55b97f013`。
- 系统 Python 3.9 的真实 `sulde-status.py --json --read-only` 正常返回结构化健康结果，
  无 TypeError、missing_sources=[]、launcher_contract_healthy=true。
  采样 checked_at=2026-09-13T10:48:52.032394 UTC；整体仍 **exit 1、ok=false、warn=true**，
  因全局历史告警存在，不能写成全局健康通过；该只读命令没有发布状态快照。
- 新 generation 当前 lane doctor：operational ready、session/task bound、pairing settled、
  unsettled=0、cas_mismatch=0、effect debt clear、Hook failures clear。
- 原 16 labels 真实 launchctl 状态 16/16 ready，无 failed/missing/retired labels。
  runtime owner active，installed_at=2026-09-13T09:48:17.074988 UTC。
  未额外 kickstart；这不代表所有后台业务逻辑重新跑过。
- 当前会话真实 PreToolUse 拒绝删除 canary；finalize 验证 marker 未执行删除后机械清理，
  独立确认 marker 不存在。proof `b320b0aa3f447d40a4535231783a4dd1bac08760a70bd9723c916e309d26fa03`，
  event `e4cb2b84f8774e1dc16dd024`，verified_at=2026-09-13T10:49:30.188470 UTC；
  doctor 证实 proof_current_generation=true。没有把 prepare 创建 marker 说成零写入。
- 从新 installed `run-mcp.sh` 启动全新 stdio 进程：initialize/tools/list/kb_status 共 3 请求，
  8 工具，exit 0。背景快照 fresh/degraded，生成于 2026-09-13T09:48:38.081017 UTC。
  未声称替换当前对话此前已连接的 MCP 进程。
- 安装器的初始 live_host_unverified、候选中的 native_permission_ui/scheduler_host unobserved
  原值保留；上述现场证据独立补足，不改旧回执。当前会话 Hook 已实际验证，完成本轮不必
  强制重启；新线程可用于加载新版 Skill/工具目录，不把静态目录重载混为本轮 Hook 证据。

## 遗留边界与新问题记录

- 全局 LIFE/heartbeat 仍 degraded（self_fixed_sections_changed），同步 migration_required；
  全局 effect_blocking=167、interventions_open=151、invalid_stores=7、event_contract_violations=274。
  未逐一核验归属，不将这些计数认定为本轮新增或已修复，也不影响当前 lane 零债务结论。
- venv 路径与 Guardian canonical 路径不一致仍是后续修复候选。本轮通过显式选择已验证且
  内容相同的既有环境完成发布，不宣称消除此兼容缺陷。
- 两条 pre-execution `--help` 组合查询被 Guardian 当作控制组合在执行前拒绝；拆成独立
  只读查询成功。记为误拦截线索，未开展源码修复，也未产生破坏性效果。
- 知识库 ap-0201 原文全文回读，用于区分宿主权限失败与真实脚本缺陷；plugin-creator
  官方发布链、intent-guardian 密封确认与独立验证、dispatch-task 同会话续行约束均保留。

### Layer1：候选环境身份与维护入口路径语义不一致

- **问题类型**：host-inconsistency / workflow。
- **目标/预期**：合法 venv 的 prepare → verify → promote 贯通，不额外反复授权。
- **触发/症状**：venv candidate 已 verified，正式 promotion 被 proposal-bound 调用门拒绝。
- **根因/证据状态**：verified；环境层保留 venv 路径，维护入口 resolve 后比较字符串，
  与上方源码及两个验证回执吻合。当前未新增自动回归测试，完整修复仍待决策。
- **排除**：非依赖内容变化、非用户拒绝、非生产写入结果未知；两个环境 same_runtime=true，
  前者没有消费 promotion，后者经新卡、新候选正式安装且独立验证通过。
- **做法与验证**：明确选择实际解释器并重新生成完整候选，不把旧环境回执套用到新环境。

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | venv 回执 lexical path 与维护入口 resolve path 不同 | apply | 路径语义冲突 | observed |
| 路由反例 | 依赖内容已变且 verifier 正确拒绝 | skip | 真实环境漂移应继续阻断 | constructed |
| 执行合格例 | 明确环境、新卡、新候选完整验证安装 | pass | 旧回执不改，不偷换环境 | observed |
| 执行失败例 | 只凭 executable hash 相同忽略 sys.prefix 和包内容 | fail | 二进制相同不证明环境相同 | constructed |

- **上浮边界**：去除用户/机器路径、版本、提交和候选标识；建议 anti-patterns，消费者为
  候选发布器与 Guardian 维护入口；修复时须同时绑定调用路径、二进制身份和依赖环境。

## 原始证据与收尾

原始证据目录：`.sulde/public-export/dev-acceptance-install-20260913/`，包含三个候选、
fresh MCP 检查脚本与 `installed-doctor.json`。历史 state/receipt 内路径不重写，归档不是执行权限。

| 文件 | SHA-256 |
|---|---|
| candidates/dva-host-20260913/state.json | `06ac9d8399517edfdb221cbb1d54a3c51d29c3528a35a0d242e2653903da7815` |
| candidates/dva-host-20260913/verification-receipt.json | `060b9f5ae11e73211559a0b448b5a3429b7dad5185603725ec7217e401bc1808` |
| candidates/dva-canonical-20260913/state.json | `f9c3c1821c3738e9e387cb51cf9953fc6c9be9e25027f1fc00f1b62dde864715` |
| candidates/dva-canonical-20260913/verification-receipt.json | `d7222f02e95b272198454ef07d1247fdfdc8f259e6d58b1f8a2ab43e48128c86` |

未重跑前一轮 2198 项全量套件；运行源码未变，本轮执行的是官方候选门和以上 live 验收。
只把最终 accepted 的运行代码/版本/报告合 dev，失败候选仅保留历史证据，不发布、不重放。

本轮交付 `b2ee8bc` 已 fast-forward 合入 dev；报告补记不改运行源码。
三个候选与现场证据（174 MiB）已完整复制到长期 dev worktree 下同名
`.sulde/public-export/dev-acceptance-install-20260913/`，递归逐文件比较 exit 0。
源任务 worktree 随后由官方 release/finalize 收尾，最终状态以该独立清理回执为准。
main 保持未变，未推送；其余历史任务 worktree 不在本轮清理范围。
