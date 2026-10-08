# H05 Recovery Lane — repair4 durable report

## 结果

H05 repair4 已关闭 FR2-H05-010 的未观测恢复事实假就绪，并保留独立 `recovery`
readiness domain。隔离候选只使用假 host、假 adapter、假 verifier、假时钟与临时本地状态；
没有执行真实 repair、uninstall、rollback、signal、Git 写、网络、设备、Figma、
安装、提交、合并或推送。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_recovery_lane tests.test_operational_readiness tests.test_sulde_statusline -v`，exit 0；实际运行 57 tests，全部 OK，0 failures/errors。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_sulde_supervisor -v`，exit 0；实际运行 12 tests，全部 OK，0 failures/errors。

## 过程

repair4 在 repair3 八路径候选上复现并关闭 FR2-H05-010：普通 `project()`/`collect()`
没有 recovery truth 时不再把空字典补成双 `True`。未提供、不完整或字段类型错误的
truth 分别输出 `recovery_truth_unobserved`、`recovery_truth_incomplete`、
`recovery_truth_malformed` 及精确字段原因，状态为 `unobserved`，代际/快照/catalog
为 `unknown`；仅显式精确布尔 true/true 可为 `ready`。

repair3 的兼容修复继续保留 `recovery` 为独立加法域，在旧精确 domain set 中显式加入
该域；状态行只在直接失败原因为
`task_lane_bound` 时使用 `任务未就绪`，其他非等待 host-interactive 故障继续使用
既有 `交互未就绪`，`恢复可用` 只作为加法后缀，不改写主失败类别。

repair4 启动前还发现全局 Codex 已从冻结 authority 的 0.149.1 升级为 0.150.1；严格
preflight 在 provider 启动前正确拒绝。经人批准，本轮只把本机已缓存且独立验真的
0.149.1 Darwin ARM64 package 临时投影到原精确 wrapper 路径，并由外层 EXIT/INT/TERM
trap 在任何终态恢复原 0.150.1。受管 run 自然成功后输出
`RESTORED codex-cli 0.150.1`，协调端独立回读同一 wrapper 为 0.150.1、摘要仍为
`134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477`。

**能力与路由**

- sulde-recovery-capability-v1：HMAC 密封 provider、session、workspace、
  installed generation、action、target、expected pre-state、allowed changes、
  issuance/expiry、独立 verifier 与 nonce；拒绝未来签发、过期、伪造、漂移和重放。
- sulde-recovery-card-v1：card identity 自身由 HMAC 密封；authority 仅为
  native typed callback，普通文本、固定短语和终端命令均无授权力。
- sulde-recovery-execution-request-v1：首次 effect 前持久化 dispatch identity；
  崩溃后只走 independent reprobe，最多两次；adapter 与 verifier receipt 精确绑定
  run/effect/action/target/result identity。
- pre-policy 路由先识别 typed recovery，再进入普通 policy。可信控制复合形状
  deny + pause=false + effect_debt=false；真实 destructive 与不可信 lookalike
  仍回到普通 fail-closed policy。

**状态矩阵**

| 普通状态 | status/doctor/readback | 写恢复动作 |
|---|---|---|
| paused / review_required | 可达，不依赖 task lane | exact Allow 后可达 |
| unavailable / schema-invalid | 可达 | exact Allow 后可达 |
| effect-debt blocked | 可达，历史只读债务追加式隔离 | exact source transaction |
| scheduler degraded | 可达 | bounded execution |
| launcher digest drift | 可达，doctor 披露 drift | repair/rollback 窄动作 |

支持的写动作：settle、abort、repair_launcher、repair_generated_bytecode、
uninstall、rollback。不存在 generic shell、arbitrary patch/delete 或
do anything 能力。

**UI 结果矩阵**

| UI outcome | 投影 | authority |
|---|---|---|
| Allow | authorized，一次消费 | native typed receipt only |
| Deny | observed，不执行 | 无 effect |
| 查看差异 | observed，不执行 | 无 effect |
| 稍后 | observed，不执行 | 新卡需新 capability |
| UI unavailable | typed unavailable + independent native path | 不回落文本/命令 |

**SLA 与输出预算**

| 轴 | 门禁 |
|---|---|
| 5 秒 | 无可见进度投影 no_visible_progress_5s |
| 30 秒 | 每窗口投影 stalled_no_progress |
| Waiting | 相同 stage/message 只记录一次，重复输出为零 |
| retry/reprobe | 总 dispatch 上限 2；durable start 后禁止再次 apply |
| terminal | succeeded/failed/cancelled/blocked 只追加一次 |
| full log | owner-only append-only supervisor journal；默认 UI 仅阶段摘要 |

## 遇到的问题

| Finding | 根因 | 处置与证据状态 |
|---|---|---|
| FR2-H05-001 | 普通 task guard 可自锁恢复入口 | typed recovery 在普通 policy 前分类；focused positive/negative 已执行通过，resolved |
| FR2-H05-002 | capability/card/receipt 绑定与 replay 边界缺失 | HMAC capability/card、exact receipt、consumed ledger 与 substitution/replay negatives 已执行通过，resolved |
| FR2-H05-003 | 缺执行、独立验真、SLA/终态和 readiness/statusline 接线 | bounded apply/reprobe、independent verifier、5/30 投影、H03 bridge 与独立 recovery domain 已执行通过，resolved |
| FR2-H05-004 | repair0 用 heredoc 包 apply_patch，触发受管临时文件拒绝 | repair3 未复用 heredoc/重定向/临时 writer；只用授权 stdin transport，resolved for H05 workflow |
| FR2-H05-005 | repair0 被协调端终止且 provider stream 无自然终态 | repair1 已自然收口；repair3 durable report 与最终自然回复补全同源证据，resolved |
| FR2-H05-006 | repair1 native adapter 把合法首行误报为非 Begin Patch | 实际 executable `/Users/eric/.codex/tmp/arg0/codex-arg0spH4D7/apply_patch` 返回 `Success`；随后 `sed -n` 回读确认 `failure_label` 与 `recovery` set 精确字节，resolved |
| FR2-H05-007 | repair2 补丁调用被 installed runtime 误分类为 destructive 并暂停 | 保持 installed-runtime observation；repair3 在 Guardian shadow + 八路径 sandbox 下通过不证明候选修复该宿主误分类，deferred to H06 |
| FR2-H05-008 | 新 recovery domain 与主状态标签造成 3 项兼容回归 | 加法扩展旧 domain set；恢复 `交互未就绪` 主标签并仅对 `task_lane_bound` 使用 `任务未就绪`；repair4 57-test gate 继续覆盖，resolved |
| FR2-H05-009 | durable report 标题不合约且把预期测试冒充执行结果 | 改为六个版本化 contract 标题，仅记录本轮实际 exit/count/output，并补齐 001..009，resolved |
| FR2-H05-010 | 缺失 truth 被折叠为空字典，两个 availability 字段又默认 `True`；statusline 只检查 `status=ready` | projection 对未观测/不完整/类型错误分型 fail closed；未知代际字段不再默认 current；statusline 同时要求 ready 与精确 true/true；新增正反例并通过 57-test gate，resolved |
| FR2-H05-011 | repair4 前全局 Codex 从冻结的 0.149.1 变为 0.150.1，严格 provider authority 拒绝启动 | 使用本机已缓存且验真的 0.149.1 做一次可逆精确投影；成功/失败均由 trap 恢复 0.150.1，协调端已独立回读版本与 wrapper 摘要；0.150.1 正式兼容验收 transferred to H06 |
| FR2-H05-012 | repair4 首个补丁的 shell 参数编码改变 payload，解析前被拒 | 拒绝尝试未修改 owned paths；改用有限 exact executable stdin transport，返回 `Success` 并完成 readback/diff，resolved |
| FR2-H05-013 | 新状态栏断言误用 waiting fixture，先进入等待分支而非目标 interactive fault 分支 | 改用既有非等待 `artifact_generation_ready` fixture；完整 57-test suite 通过，resolved |
| FR2-H05-014 | 首个 bytecode comparator 手抄 expected 常量错误，产生 comparator 自身失败 | 改为结构化 inventory 比较；7 个继承 pyc 的 hash/size/mtime 不变，`new=0; modified=0`，resolved |

## 解决方式

修复没有删除或隐藏已显式验证的 recovery availability，也没有把普通交互故障改写为
task 故障。projection 先验证 required availability 字段与可选代际字段的类型，再决定
`ready`；statusline 通过同一 exact true/true 条件做防御式消费。readiness、statusline、
native typed card、execution journal 与 supervisor bridge 继续各自消费同一窄恢复事实。

**验证命令与实际计数**

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_recovery_lane tests.test_operational_readiness tests.test_sulde_statusline -v`：exit 0；57 tests，OK。
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_sulde_supervisor -v`：exit 0；12 tests，OK。
- `PYTHONDONTWRITEBYTECODE=1 python3 -c 'import ast,json,pathlib; task=json.loads(pathlib.Path(".codex-agent/r2-h05-recovery-lane-repair4.task.json").read_text()); paths=[path for path in task["owned_paths"] if path.endswith(".py")]; [compile(ast.parse(pathlib.Path(path).read_text(), filename=path), path, "exec") for path in paths]; print(f"AST parsed={len(paths)}; compiled={len(paths)}; bytecode_written=0")'`：exit 0；`AST parsed=7; compiled=7; bytecode_written=0`。
- `git diff --check`：exit 0；0 whitespace errors。
- 冻结范围 comparator（`git status --porcelain=v1 -z --untracked-files=all` 的 exact-set 检查）：exit 0；`owned_changed=8; coordinator_inputs=2; unexpected=0`。coordinator inputs 是 repair3 与 repair4 开始前已存在且未修改的两个 brief。
- `shasum -a 256` 与 `stat -f` 对七个既存 ignored `.pyc` 前后核对：两次输出逐项相同；repair4 新增/改写 bytecode 为 0。遵照“不清理”保留 repair2/独立 `py_compile` 已存在的 7 个 artifact。

**Requirement traceability**

| Requirement | 直接证据 |
|---|---|
| R2-GRANT-BROKER | exact native Allow/Deny/查看差异/稍后与一次消费；文本无 authority |
| R2-RECOVERY-SUPERVISOR | durable run/stage、5/30 秒、bounded reprobe、single terminal、H03 bridge |
| R2-RECOVERY-LANE | sealed capability/card、pre-policy narrow route、完整状态/动作/negative matrix |
| PROGRAM-GOVERNANCE | 八路径范围、FR2-H05-001..014 disposition、实际命令/计数、限制与沉淀候选 |

**Changed paths**

1. scripts/kb/recovery_lane.py
2. scripts/kb/intent_guardian_parts/recovery.py
3. scripts/kb/operational_readiness.py
4. scripts/kb/sulde-status.py
5. tests/test_recovery_lane.py
6. tests/test_operational_readiness.py
7. tests/test_sulde_statusline.py
8. guardian-r2-program/reports/H05-recovery-lane.md

## 遗留风险与建议

- 仅完成 isolated deterministic acceptance；不声明 live host、Windows、
  Claude、生产安装/卸载、H04/H06、release、dev/main 或真实外部效果验收。
- H03 bridge 只消费显式 record_recovery_event adapter；宿主未提供桥时 fail closed，
  不把普通 task lane 当作替代通道。
- Skill catalog 仍需新会话发现；只有当前 Hook 控制入口可热重绑定。
- FR2-H05-007 仍是 installed runtime 的未关闭观察；本轮 shadow Guardian 与封闭文件
  sandbox 是运行选择，不是误分类已修复的证据。应由 H06 用 installed-runtime 回归处理。
- FR2-H05-011 的可逆投影只证明冻结 0.149.1 authority 下的受管 repair4 与恢复原版本；
  它不证明当前 0.150.1 已被 runtime authority 正式支持。H06 必须在不降级全局 CLI 的
  条件下完成 compatibility/preflight、live host 与回滚验收。
- 7 个 ignored `.pyc` 在 repair3 前已存在且未变化；本任务无权限清理，协调端若要求干净
  bytecode 树，应在独立获批维护任务中处理，不能计作 H05 候选写入。

## 沉淀候选

### 候选 A：恢复入口必须先于被恢复的普通策略

- 语境：可信恢复命令因 composition 违规被拒后，普通 guard 又把任务暂停。
- 证据状态：verified。
- 路由正例：sealed recovery request 在普通 lane paused/schema-invalid 时进入
  narrow recovery route。
- 路由反例：不可信同名命令或真实 destructive 仍进入普通 fail-closed。
- 执行正例：invalid composition 返回 deny、launch=false、pause=false、
  effect_debt=false。
- 执行反例：把可信复合命令降级为普通 read 或先调用 ordinary guard。

### 候选 B：effect 前 durable dispatch identity 才能安全 reprobe

- 语境：adapter 完成效果后进程在 receipt 前崩溃。
- 证据状态：verified（deterministic failure injection）。
- 路由正例：存在 durable dispatch-start、缺 receipt 时只允许 independent reprobe。
- 路由反例：prepare 前失败且从未建立 dispatch identity，可做首次 apply。
- 执行正例：apply 计数 1、reprobe 计数 1、terminal 计数 1。
- 执行反例：缺 receipt 就再次 apply，或无限 poll/retry。

### 候选 C：Hook generation 与 Skill catalog 生命周期不可合并

- 语境：旧会话可热重绑定控制 Hook，但静态 Skill catalog 仍是启动快照。
- 证据状态：verified。
- 路由正例：doctor/statusline 分别显示 current/old Hook、stale snapshot 与
  skill restart required。
- 路由反例：用单一需要重启掩盖当前 Hook 已恢复，或声称 Skill 已热更新。
- 执行正例：task/scheduler/launcher failure 不隐藏 recovery available。
- 执行反例：普通 readiness 红灯把恢复通道一并标成 unavailable。

### 候选 D：readiness truth 缺席时必须保留未观测语义

- 语境：投影把缺席 truth 折叠为空字典，再以乐观默认值生成 ready，UI 据此显示假可用。
- 证据状态：verified（deterministic projection/statusline regression）。
- 路由正例：只有显式、类型精确的双 availability true 才进入 ready 投影。
- 路由反例：`None`、缺字段、字符串布尔或 malformed generation 字段进入 unobserved。
- 执行正例：unknown snapshot/hook/catalog 保持 unknown，statusline 不追加恢复可用。
- 执行反例：用 `dict.get(..., True)` 或仅信任派生 `status=ready`。
