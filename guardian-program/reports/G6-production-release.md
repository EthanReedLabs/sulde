# G6 正式发布与 live 验收

## 最新结论（revision 22，Codex-hosted G6 发布门禁已验收）

`2026-08-26` 的 release preflight 已确认 G6 task 内容实际位于
`dev@870c5e73ed97fe7b5fd602e9a932815f709c2b8c`，而不是 revision 21 报告中仍保留的
“task 尚未合入 dev”历史状态。协调端从该精确提交创建独立 clean clone，使用官方
`scripts/kb/run-isolated-tests.py` 完整执行：总计 1449 项，其中 1443 pass、6 skip、
exit 0，耗时 385.710 秒；运行前后 clone 均 clean，且无 `__pycache__`/`.pyc`。

首次预检 clone 误用了 `--single-branch`，使测试内部无法再从该 clone 的 `main` 分支创建
fixture，产生 15 个同源 setup error；该轮其余用例通过。补齐指向
`main@c461cba023994c1d3eb7fc100751181120f56203` 的本地与 remote-tracking 引用后，
最小内部 clone 探针和上述完整第二轮均通过。该 finding 只属于预检仓库形状，不是源码
回归，也没有通过修改测试来消除失败。

真实 Claude live 仍未验证，且当前 Claude 额度不可用。用户明确决定不让这一不可用的
另一宿主阻断已独立成立的 Codex production release：G6 的当前正式门禁调整为
**Codex production authority/live accepted + 双宿主静态契约通过**；Claude
SessionStart/UserPrompt/tool-boundary live canary 延期为 R2 的独立进入条件。在 live
证据存在前，任何报告和发布说明都不得宣称 Claude production accepted，也不得用
synthetic callback、源码测试或 Codex 观测代替。

revision 22 只允许更新本报告与总纲报告，并使用仓库自有 `agent-runtime.py` 完成受管
task → `dev` → `main` 本地快进。最终合并必须以 release worktree 的双文件提交、最终
clean-clone gate、三方 clean 状态和精确 Git refs 的独立回读为准；本报告不以自引用提交
哈希冒充合并证据。本轮不 push、不重装、不切 generation、不修改 production ledger，
也不创建或启动 R2。

## revision 21（历史发布边界，Codex production live 已验收）

revision 14 已通过 v2 no-bytecode cachebuster/install grants 正式安装
`0.2.5+codex.20260825145516-5bb47561a9`；两个 grant 各消费一次，artifact、installed
runtime 与工作区 release 输入的 bytecode 检查均为零。revision 15 随后从该 installed
generation 生成 scheduler/launcher grants，scheduler 精确命令只执行一次并成功重协调
15/15 `com.sulde.*` labels。`runtime-owner.json`、`deployment-generation.json`、runner seal
与 generation 一致，可信 OS 边界的 `/bin/launchctl list` 显示 15/15 loaded、退出码均为
0；同一注册 verifier 在可信 OS 边界返回匹配证据。

但 scheduler 的 PostToolUse Hook 运行在无 launchd 可见性的 sandbox 中，无法完成同一
注册 verifier，因而把已成功的 attempt 留在 `verifying`。真实 UserPromptSubmit 恢复边界
也受相同 sandbox 限制，pending verification 仍为 1；这不是 scheduler 失败，也不能通过
重跑命令、人工删账本或伪造 hook 闭合。launcher grant 尚未消费，避免在 scheduler 结果
正式结算前继续生产变更。

revision 16/17 把修复严格限制为公开 `reconcile-verifications` CLI：它只调用现有
`reconcile_pending_verifications` reducer，在受信宿主边界运行已注册独立 verifier，绝不
重放原 effect；可信 Guardian launcher 将其识别为 agent control，伪造 launcher 和 shell
composition 不获得控制面身份。5 项直接回归为 5/5，完整 Intent Guardian 文件级套件为
193/193。revision 17 仅为满足 `agent-runtime commit` 的 clean-worktree 不变量，把 revision
14 已批准且已安装的唯一 manifest version 纳入同一精确路径集；没有再次生成 cachebuster。
精确 source commit 为 `23a3c75118132f30321bf5b37653d959621cc6b0`，tree 为
`4880e7ff3ae2cf861efb577d15642f3514d8a58b`。包含全部 remote refs 的 clean clone 固定在
该提交，使用 Sulde Python 3.10.7 venv 与 `-B` 运行官方 `run-isolated-tests.py`：1448 项为
1442 pass、6 skip、exit 0，耗时 382.947 秒；运行前后 clone 均 clean 且无
`__pycache__`/`.pyc`。首次从 Codex 外层 sandbox 启动时，macOS `sandbox-exec` 因不允许
嵌套而在测试发现前 exit 3；改在受信 OS 边界运行同一命令后通过，未改源码或生产状态。

在 revision 17 边界，修复版生产安装、pending reconciliation、launcher 刷新及最终
doctor 仍待执行，因此该阶段没有提前宣称 G6 accepted。

revision 18 首先从受信 OS 边界执行已发布源码的 `reconcile-verifications`。公开 CLI 正常
运行但返回 `reconciled_count=0`、pending 仍为 1；同一 grant ID 重算一致，15/15 launchd、
deployment/owner/generation/runner seal 全部匹配，且公开
`scheduler_reconcile_verification` 单独返回精确 content proof。由此定位到 proof 之后的
`verify_from_read` capability matcher：它只列出 cachebuster/install 两个 Bash machine
verifier，漏掉 scheduler/launcher。revision 18 的 cachebuster/install grants 均为零消费，
没有生成新 version 或执行安装；revision 19 只补两个精确映射和端到端终态回归。

revision 19 的精确源码提交为 `edf320edb6bdcd36a671b646c9ade7ffa9fb9ac1`，tree 为
`93afb30bec408ffbbc69d13ee0197253875941e9`。修复只允许四个明确 maintenance verifier
从 `tool:Bash` effect 进入 machine-verifier 结算路径：既有 cachebuster/install，加上
scheduler reconcile/launcher refresh；任意别名、缺失能力或普通 `tool:Read` 仍不能结算。
新增端到端测试覆盖 scheduler 与 launcher 从 typed effect、`verifying` 到唯一
`system_verified` 的完整链，而不只断言 verifier 函数能产生 proof。定向 2/2、完整
`test_intervention.py` 69/69、Intent Guardian 193/193 全部通过。

包含全部 remote refs 的 clean clone 固定在该提交，在受信 OS 边界使用 Sulde Python
3.10.7 venv、`PYTHONDONTWRITEBYTECODE=1` 与 `-B` 运行官方
`run-isolated-tests.py`：1449 项为 1443 pass、6 skip、exit 0，耗时 382.488 秒；运行前后
clone 均 clean 且无 `__pycache__`/`.pyc`。隔离器末尾观察到生产账本在测试期间有当前宿主
并发事件，并将其隔离在可验证只读边界之外；这些生产事件没有进入 clone、测试状态或源码
通过证据。

revision 20 先由当前 Codex 原生卡批准“只重新检查”旧 scheduler attempt，随后从受信
宿主运行公开 source `reconcile-verifications`。它没有重放 scheduler，返回
`reconciled_count=1`、`pending_verifications=0`；effect truth 从 7/8 变为 8/8
`system_verified`，独立证据来自 `tool:sulde_scheduler_reconcile_verify`。

同一 revision 的正式发布卡同时声明 `local_write + external_write`，因此生成了两个精确
v2 grant；只有 `external_write` 的未批准初稿因最小权限推导得到零 grant，未执行任何动作
并被等价卡替换。正式卡的 cachebuster 与 installer grant 各消费一次、各自独立验证为
`system_verified`，总 effect truth 为 10/10 `system_verified`，pending 和 open
intervention 均为零。新版本为 `0.2.5+codex.20260825160039-6485efd444`：

- artifact：`/Users/eric/.sulde/artifacts/sulde-0.8.4-0.2.5-codex.20260825160039-6485efd444/codex`；
- installed plugin：`/Users/eric/.codex/plugins/cache/sulde-local/sulde/0.2.5+codex.20260825160039-6485efd444`；
- plugin tree：`e92e7d0999cae1a7d1f6db03f5eff2b19d4269e371e02d3a15b7b5575811e659`；
- runtime tree：`dc083caec0982ecc0d97eda6b1c9b6cf0b3bf687c4c79ba09325c6f0e95b1bef`；
- generation：`0.2.5+codex.20260825160039-6485efd444:dc083caec0982ecc0d97eda6b1c9b6cf0b3bf687c4c79ba09325c6f0e95b1bef`；
- native runtime authority：`d955c84f176666903e601e44cf0bd025ff5089676ccd7d625430e3e472889492`。

installer exit 0，状态为预期的 `installed_degraded`：artifact、registry/cache、稳定 launcher、
native authority 与 synthetic smoke 已通过；scheduler owner 仍绑定上一 generation，且新
runtime 尚缺真实重启会话 live evidence。source、artifact、installed plugin 三处扫描均无
`__pycache__`/`.pyc`。

revision 21 只从 revision 20 已安装 generation 生成 scheduler 与 launcher 两个一次性
grant，没有再次执行 cachebuster 或 installer。scheduler 精确命令消费一次并 exit 0，随后
公开受信 reconciler 返回 `reconciled_count=1`、`pending_verifications=0`；15/15
`com.sulde.*` labels 均由新 generation 管理并 loaded，missing/failed/retired 为空。launcher
精确命令也只消费一次并 exit 0，返回 `SULDE LAUNCHERS: READY spec=10 count=6`；同一公开
reconciler 再结算 1 项，pending 保持为 0。两个 grant 均为唯一 `system_verified` 终态，
effect truth 达到 12/12 `system_verified`。

当前会话随后使用 Codex 原生 `resume` 续接同一 session
`01a00d6f-65b3-7663-b51b-f88684ffa561`，没有创建新 authority lineage，也没有伪造
continuation proposal。续接后的真实 SessionStart 与 UserPromptSubmit 由当前 installed
runtime 观测；稳定 launcher 的最终 doctor 为 `status=ready`、
`operational_status=ready`、reasons 为空。artifact generation 与 runtime tree 精确匹配，
scheduler 15/15 ready，effect debt clear，native pairing settled 且
`cas_mismatch=0`、unverified=0；interactive 全部门均为 true，session、prompt、tool
guard/result、turn reconcile 与 interactive status 均为 `live_verified`，invalid row 为 0。

旧 projection 字段 `deployment_status` 仍显示 `installed_live_unverified`，但同一份 doctor 的
权威 operational、interactive、artifact、scheduler、pairing 与 effect gates 全部为 ready。
本轮将它记录为非阻断的可观测性标签滞后，不用修改账本或扩大源码任务来“刷绿”。Codex
production authority/live acceptance 已为 `accepted`；真实 Claude live 仍缺失，因此双宿主
G6 formal acceptance 继续为 `blocked`。当前正式边界仍是不修改或删除 active JSON、events
JSONL、effect ledger，不重放任何生产 effect，不合并、不 push。

## revision 12 基线（历史）

revision 10 已用旧生产 runtime 的一次性 v1 bootstrap authority 成功发布
`0.2.5+codex.20260825141150-f9c5caf8ac`；cachebuster 与 installer grant 各消费一次，
独立 verifier 均通过，artifact、installed generation 与工作区均无 bytecode。revision 11
随后由新 runtime 生成 scheduler/launcher typed grants，但第一条精确 scheduler 命令在
PreTool 阶段被拒绝，生产 scheduler 未重载，grant 未消费，open event、pending
verification、effect debt 和 lane pause 均未增加。

该 live blocker 的根因不是用户授权或命令参数：proposal binder 把源码仓
`install-agents.sh` 的摘要写入 grant，而官方 `stage_plugin.neutralize_launchagent_paths`
会把其中的机器路径物化为 portable token，installed artifact 的真实字节和源码不同；
执行 matcher 正确校验 installed script，因而不可能匹配该 grant。旧回归只用 `copy2`
模拟 installed runtime，掩盖了真实 staging 变换。

revision 12 将发布协议冻结为两阶段：cachebuster/install proposal 只能发布 artifact；只有
目标 generation 已安装后，scheduler/launcher proposal 才能绑定 installed artifact 的
真实脚本摘要。目标 installed script 不存在时 binder fail-closed；脚本漂移后 classifier
可以识别 maintenance 形状，但不能获得旧 grant authority。定向 3/3 与完整 Intent
Guardian scoped suite 191/191 已通过。精确源码基线提交为
`44cc913b961f148060ea18156d5ad14e1be995f5`；包含全部 remote refs 的 clean clone 使用
Sulde 受控 Python 3.10.7 venv 运行官方全套，1446 项为 1440 pass、6 skip、exit 0，
耗时 319.844 秒，运行前后 clone 均 clean 且无 `__pycache__`/`.pyc`。一次先行环境检查
误用了缺少 numpy/PyYAML 的 Homebrew Python 3.14，因此产生 1 error/1 failure；该无效
运行未用于验收，也没有安装依赖或改变源码。当前生产保持 r10 的新插件 generation、旧
scheduler generation 和稳定 launcher，没有重放 r11，也没有直接修改 installed cache
或账本。

G6 的两个既有源码 blocker 已按冻结修复卡闭合并部署到生产 Codex 插件。最终审计又
发现一项不能隐藏的 authority blocker；revision 9 已完成该 blocker 的源码修复与完整
隔离验证，但尚未按新 typed profiles 发布。加上 Claude live 缺失，当前仍有两项正式发布
blocker：生产 authority 闭环未验证、Claude live 未验证。因此 G6 formal acceptance 仍为
`blocked`，task 分支没有合入 `dev` 或 `main`。

本轮没有扩张任务图，完成的 exact 事实为：

- 修复提交：`620e71aa19df1b11806c9a74f06e115df7fe322d`；源码证据提交：
  `55026bee30537ba8b6787596a17fa81d1ea45671`；唯一 cachebuster 提交：
  `ad8d303d252746c672782fa96571db11908987eb`。
- revision 9 authority 修复提交：`0276a02324470b140300c40e710b0f3901e6ed60`。
  新增 versioned v2 no-bytecode wrapper profiles，保留 v1 历史恢复；scheduler reconcile 与
  launcher refresh 各自拥有一次性 grant、精确 argv/script/tree binding 和独立 verifier。
- 高风险 enforce 中，已知正式维护入口未匹配 proposal-bound profile 时在执行前拒绝；
  普通低风险 unknown 仍保持既有 degraded-observe 自主路径。`--help`/`--dry-run` 保持 read。
- revision 9 scoped Intent Guardian 套件为 199/199；精确 clean clone 固定在 `0276a023`，
  官方全套共 1446 项（1440 pass、6 skip）、exit 0，运行前后 clone 均 clean 且无
  `__pycache__`/`.pyc`。
- 官方 clean-clone 套件为 1441 通过、6 skip；Intent Guardian 194/194；G6 定向模块
  98/98，双运行时与 Windows bootstrap 22 通过、1 skip，operational/P0 31/31，
  Codex transactional installer 39/39。
- 官方事务 installer 已安装
  `0.2.5+codex.20260825122126-7d2b27bf67`；runtime tree 为
  `b696980bf502830e724cd2512c87f08d448392b093958e134b34cc9845ea86ac`。
- 安装命令为避免 bytecode 加入了 `PYTHONDONTWRITEBYTECODE=1` 和 Python `-B`，因此没有
  匹配 r8 的 exact `codex-plugin-install-v1` grant。Guardian 将该 Bash 误分类为
  `unknown` 并在 enforce 模式 degraded-allow；官方 installer 的独立后置证明全部通过，
  但安装 grant 未消费，不能冒充 proposal-bound authority 闭环。
- 15 个 Codex jobs 已原子重协调到该 generation；可信 doctor 为
  managed/loaded `15/15`，missing/failed/retired 均为 0。
- 新版安装树真实执行 `bootstrap.sh --launchers-only --host codex` 后，launcher
  manifest 仍保留 runner path 与
  `scheduler_runner_sha256=d178ba631a4aff36934ead0802b7e50af428c4c3fbdc2d52664468b5e88f00e2`，
  且与 runtime owner 一致。
- 主工作区 v2 只读 cut 为
  `926caca021e3182bd532318690647dc4efdb5da85da8b9f721f5e6b9af912aae`；
  7/7 sources 稳定，actionable pending native transaction 为 0，5 条旧版 unsealed
  prepared 仅计入 `historical_unsealed_native_transactions`，blockers 为空。
- Codex canary `01a038e7-d5f8-74b1-85de-4a800a926b7e` 返回
  `G6_CODEX_COMBINED_CANARY_OK`；同一新版 runtime 记录了真实 SessionStart、
  UserPromptSubmit、PreToolUse/PostToolUse 与 Stop。新 lane 保持 `review_required`，没有
  继承旧 authority。
- 可信进程清单中没有 Claude CLI 或 Claude Desktop；未启动另一宿主，未用 synthetic
  callback 替代 live 证据。

## 初始发布验收快照（revision 4，历史）

`2026-08-25T11:23:18Z` 的初始发布验收曾因 unsealed prepared、launcher/scheduler
seal 组合缺陷和 Claude live 缺失三项而 blocked。下列安装、bytecode 事故、scheduler
恢复和旧 cut 内容保留为当时的审计快照；其中前两项已由上方 revision 8 证据取代。

## 初始冻结发布输入（历史快照）

- task branch：`feature/guardian-runtime-control-plane`
- release runtime commit：`bbef99c8b241590701816ab418e8ca7da8a372fb`
- release tree：`7196ce6b3eddb6b6e17d202df73894f608d5a9de`
- plugin version：`0.2.5+codex.20260825101651-5fc6c9c7ec`
- cachebuster：本轮唯一一次，已包含在 release commit；没有生成第二个 cachebuster。
- worktree：安装前后均 clean，未修改 release 源码。

最终 release commit 的预安装证据：

- G0-G5/核心定向：307/307 通过。
- 全部 Intent Guardian：194/194 通过。
- 官方 clean-clone 隔离套件：1437 项通过，6 项 skip，exit 0。
- `git diff --check` 通过。
- clean clone 固定在 exact `bbef99c8`，测试期间生产 KB 的并发变化没有进入 clone 或
  源码树。

## 安装与 generation

官方事务 installer 成功安装：

- artifact：`/Users/eric/.sulde/artifacts/sulde-0.8.4-0.2.5-codex.20260825101651-5fc6c9c7ec/codex`
- installed plugin：`/Users/eric/.codex/plugins/cache/sulde-local/sulde/0.2.5+codex.20260825101651-5fc6c9c7ec`
- generation：`0.2.5+codex.20260825101651-5fc6c9c7ec:d38abce27ad6249c6b4c29eda7ef531312689da178de348afba445607e0e7f32`
- runtime tree：`d38abce27ad6249c6b4c29eda7ef531312689da178de348afba445607e0e7f32`
- plugin tree：`e3f32dd5077af725b34ab83caf69c0fce5cfd5e39eb567d613e36a802155f1da`
- native runtime authority：`735c9dc88717df0436df065f735fffb134d9a6be64185dbe704209a208e1398a`

首次 installer grant 因未来树摘要与最终提交树摘要不一致，在任何生产状态变化前正确
失效。revision 3 只把同一安装动作重新密封到 exact final tree，没有重跑 cachebuster。
已核对显式发布输入均为 0644；本次漂移不是 Git 0400 物化成 0644，也没有 mode-only
组合能复现旧摘要。

## bytecode 事故与 bootstrap 自锁

为关闭主账本一笔已有 durable Allow 的历史事务，本会话直接用 Python 导入 installed
runtime，却漏设 `PYTHONDONTWRITEBYTECODE=1`，生成 34 个 `.pyc` 与 3 个
`__pycache__`。这是执行入口错误，不是 Codex canary 自发污染。

后果形成 bootstrap 自锁：

- stable launcher 因 runtime digest changed fail-closed；
- 同一 Hook 故障使 bytecode repair 的 native proposal 无法配对；
- 未配对 Allow 没有被当作 authority，也没有重放。

按发布件明确的 break-glass 路径执行：

`bootstrap.sh --launchers-only --repair-generated-bytecode --host codex`

修复器先证明忽略 bytecode 后的 runtime tree 与 sealed generation 完全一致，才清理
34 个文件和 3 个目录。修复后：

- `.pyc`/`__pycache__` 扫描为零；
- stable launcher `healthy=true`；
- runtime tree 仍为 `d38abce...`；
- 旧提案因 material world 改变被拒绝，重新生成的 revision 4 通过 fresh
  PermissionRequest 正式 applied，没有复用旧 request/receipt。

## scheduler

bytecode repair 重建 `.sulde-launchers.json` 后丢失 `scheduler_runner_sha256`，而稳定
runner 把该字段作为 generation fence 的必需输入。可观察结果是：

- 15/15 labels 仍 loaded；
- `com.sulde.codex-harvest` 最近退出码为 1；
- runner dry-run 明确报 `immutable runtime tree digest drifted`；
- runtime tree、owner、deployment descriptor 和 runner 文件摘要实际均未漂移，唯一缺失
  字段位于 launcher manifest。

没有修改源码。官方 `install-agents.sh` dry-run 证明同一 generation、同一 15 个 labels、
零未知/retired actor 后，事务化重协调原有 jobs；沿用用户已确认的“15 个 Codex 定时任务
可发送脱敏本地上下文”边界。终态：

- loaded/managed：15/15；
- missing/failed/retired：0/0/0；
- scheduler generation、runtime owner、runtime tree、runner seal 全部匹配；
- harvest 通过同一 stable runner 的内建 dry-run：72 个文件、79 个新候选、0 parse error、
  0 failed file；dry-run 未更新数据库或 state；
- 当前旧会话 doctor：artifact ready、scheduler ready、effect debt clear、native pairing
  settled、interactive ready，整体 `ready`。

该运行态恢复不关闭源码缺陷：未来单独执行 launcher-only refresh 仍可能再次清掉 scheduler
seal，因此 FG6-003 保持 release blocker。

## Codex 与 Claude live

### 当前旧 Codex 会话

会话 `01a00d6f-65b3-7663-b51b-f88684ffa561` 通过真实宿主 doctor：

- SessionStart/UserPrompt 通过 verified hot rebind 延续；
- tool guard/result 来自当前 installed runtime；
- 当前 task lane bound；
- operational readiness `ready`，全部交互 gate 为 true。

### 新 Codex 会话

launcher 损坏期间创建的 `01a03895-63a8-7262-897d-9b718eb3bafa` 只证明 Codex 模型能
响应，Guardian 没有 live observation，因此明确不计为 canary。

修复后新建 `01a0389f-4ade-7bd0-952d-dcea9211fea1`，模型返回
`G6_POST_REPAIR_CANARY_OK`。真实 current-runtime 证据包含 SessionStart、UserPromptSubmit
与 TurnReconcile；新 lane 正确处于 `review_required`，没有继承旧会话 authority。这是
新会话边界的预期 fail-closed 结果。

### Claude

完整隔离套件包含双宿主静态 contract/E2E 覆盖；当前进程清单中没有活跃 Claude 宿主。
因此 Claude static 通过、live 未验证，不能用 synthetic callback 替代。

## 历史 intervention 与 cutover

主 Sulde contract 为 revision 142。原唯一已密封且停在 `approval_decided` 的历史 effect
事务，恢复器只读取已有 durable Allow 与 intervention 后置证据：先进入
`effect_applied`，随后因 contract CAS 已演进而安全 `superseded`。没有重跑原外部操作。

最终只读 legacy cut：

- cut：`084ca967d1e9e1d45d35bd195175b877e2c10b8843dc99420a557815dc5c3d7e`
- source fingerprints：7/7 稳定；
- open event/pending verification/open approval/open intervention/blocking effect/paused lane/
  integrity breach：全部 0；
- pending native transaction：5；
- 唯一 blocker：`pending_native_transactions:5`。

这 5 笔只有旧版 `prepared` 行，没有 durable seal、operation 或 Allow。新版明确规定它们
只能作为诊断历史存在；任何 supersede/cancel 都需要伪造当前不存在的 authority。故本轮
不删除、不改写、不补造，cutover 不生成 authority binding。

外部产品 workspace 的历史债务不在冻结 G6 范围内，没有读取后执行、重试、删除或迁移。
全局状态仍会聚合其他历史 workspace/store 的旧警告；它们不冒充当前 G6 operational
readiness，但也没有被本轮宣称清零。

## Finding 处置

| Finding | 结论 | 处置 |
|---|---|---|
| FG6-001 | future-tree grant 与 final tree 不一致 | `fixed_current`：零状态变化失效后，以 revision 3 重新密封 exact tree |
| FG6-002 | 直接 Python 导入 installed runtime 生成 bytecode 并自锁 launcher | `fixed_current`：官方摘要受限 repair；后续只用 stable launcher/no-bytecode 入口 |
| FG6-003 | launcher-only refresh 丢失 scheduler runner seal | `fixed_current`：同 generation/owner/tree 严格组合后保留 runner seal；真实 launcher-only refresh 与 15/15 scheduler 通过 |
| FG6-004 | 5 笔 unsealed prepared 历史事务阻断 cutover | `fixed_current`：exact legacy 形态只读归为历史诊断；production v2 cut pending=0、blockers=0，未补造 authority |
| FG6-005 | 无活跃 Claude live host | `deferred_r2_gate`：只保留 static 证据，不造假 canary；不再阻断 Codex-hosted G6 发布，但在真实 live 前不得宣称 Claude production accepted |
| FG6-006 | sandbox 内 readiness 可把 launchctl/CAS 权限失败误报为 0/15 | `fixed_current`：最终证据只采用可信宿主边界，sandbox 结果仅作 finding |
| FG6-007 | exact installer grant 因 no-bytecode wrapper 未匹配，unknown Bash 在 enforce 中被 degraded-allow | `fixed_current`：revision 20 的 v2 no-bytecode cachebuster/install grant 各消费一次并独立 `system_verified`；未回退 unknown allow |
| FG6-008 | scheduler 已成功，但 Hook sandbox 无法观察 launchd，注册 verifier 永久留在 pending | `fixed_current`：revision 20 从可信宿主公开入口结算 1/1 pending，不重放 scheduler、不降低 verifier |
| FG6-009 | `agent-runtime commit` 的 clean-worktree 不变量与先前批准但未提交的 manifest 形成提交自锁 | `fixed_plan`：revision 17 把既有唯一 manifest 纳入精确路径集；禁止 stash/revert、直接 commit 或再次 cachebuster |
| FG6-010 | scheduler/launcher verifier 能生成正确 proof，但 effect matcher 未授权这两个注册 capability | `fixed_current`：revision 19 源码与 1449 项 clean-clone 通过，revision 20 真实 scheduler 历史 attempt 由新 matcher 结算为 `system_verified`；任意别名与普通 read 仍拒绝 |
| FG6-011 | 已 applied 的 revision 没有 current proposal，`prepare-continuation` 无法为仅需重启的 live 验收生成 capsule | `fixed_workflow`：使用 Codex 原生 exact-session resume；新 SessionStart 重新建立 live evidence，未创建虚假 revision 或转移 authority |
| FG6-012 | 全部权威 readiness gate 已 ready，但 legacy `deployment_status` 仍为 `installed_live_unverified` | `observed_nonblocking`：保留原值与完整 doctor 证据，不编辑 projection；后续单独判定标签派生语义，不扩张 G6 |

## 发布与合并决定

- 当前 installed Codex runtime：revision 20 新 generation 已安装，revision 21 已把
  scheduler/launcher 切换到该 generation；cachebuster、installer、scheduler 与 launcher
  四类 authority 均唯一消费并由独立 verifier 闭环。最终 effect truth 为 12/12
  `system_verified`，scheduler 15/15，当前 Codex exact-session live doctor 为
  `operational_status=ready`。
- Codex production acceptance：`accepted`。
- G6 当前正式发布门禁：`accepted_for_codex_hosted_release`；双宿主静态契约已通过，
  Claude live 为 `deferred_r2_gate`，不是本次 Codex 发布的 blocker。
- G6 task → `dev`：已在本次收口前到达 `dev@870c5e73`；revision 21 的“未执行”是历史快照。
- 本次文档收口 task → `dev` → `main`：只能由 `agent-runtime.py` 在 exact SHA、clean、
  ancestor 与最终 clean-clone gate 全部通过后依序快进；最终 refs 回读是合并完成的权威证据。
- push：未执行。
- production ledgers：只追加原生决策、公开 reconciliation 与注册 verifier 结果，未编辑、
  删除、重排或重放旧 scheduler。

## 沉淀候选

### 候选一：恢复器诊断入口也必须 no-bytecode

- **问题类型**：workflow / anti-pattern update
- **语境**：对不可变 installed runtime 做只读/幂等恢复诊断。
- **根因**：直接解释器导入未密封 `PYTHONDONTWRITEBYTECODE`，诊断改变了被校验树。
- **证据状态**：verified。
- **正确样本**：stable launcher 或 Python `-B`/no-bytecode 环境，运行前后 tree digest 相同。
- **失败样本**：普通 Python 导入后再运行 immutable launcher gate。
- **建议路由**：并入现有“测试入口生成 bytecode 污染不可变 runtime”条目。

### 候选二：独立刷新一个 authority manifest 时必须保留跨子系统 seal

- **问题类型**：bug-fix / control-plane composition
- **语境**：launcher-only repair 与 generation-fenced scheduler 共用 manifest。
- **根因**：launcher writer 以自身 schema 全量重建文件，丢失 scheduler writer 后加的 seal。
- **证据状态**：verified。
- **正确样本**：统一 schema/reducer，或 launcher refresh 后原子调用 scheduler reseal；15/15
  jobs 在 refresh 前后均 ready。
- **失败样本**：单写者名义上各自正确，但共享 projection 被后写者全量覆盖扩展字段。

### 候选三：需要宿主特权观测的 verifier 必须有公开安全边界

- **问题类型**：workflow / control-plane recovery
- **语境**：scheduler 外部写入已经完成，PostToolUse 需要读取 launchd 证明 15/15 live。
- **根因**：同一个注册 verifier 只能从 Hook sandbox 自动调用；sandbox 无 launchd 可见性，
  真实成功被永久投影为 pending。
- **证据状态**：verified。
- **正确样本**：公开、受信、幂等的 verifier-only CLI；只消费注册 proof，经 attempt-id CAS
  写入 `system_verified`，不重放原 effect。
- **失败样本**：重复 scheduler、人工删除 pending、伪造 SessionStart，或降低外部写入验证。
- **建议路由**：新增 control-plane safe-host verifier boundary 条目，并关联 sandbox
  readiness 误判案例。
- **建议路由**：anti-patterns；消费者包括配置层、generation manifest、scheduler installer。

### 候选三：new-lane live canary 的原始观测与聚合 readiness 不应互相冒充

- **问题类型**：observability projection mismatch。
- **语境**：新 Codex session 在同一进程完成 SessionStart、UserPromptSubmit、
  PreToolUse/PostToolUse 与 Stop；该 lane 按设计为 `review_required`。
- **证据状态**：inconclusive。append-only capability rows 可证明五类事件来自同一 current
  runtime，但精确 doctor 在工具完成后把 `prompt_control` 聚合为 `unobserved`；尚未证明
  是 active-turn 窗口缺陷还是 review-required lane 的有意降级语义。
- **路由正例**：分别报告 event-level live evidence、task-lane authority 与 aggregated
  operational readiness，不把任一层的状态替代另外两层。
- **路由反例**：看到 canary marker 就宣称 lane ready，或看到 aggregated degraded 就否认
  已存在的签名 host events。
- **执行合格例**：保留原始事件和精确 session doctor，后续用确定性测试复现后再决定是否
  修改 projection；本轮不扩张源码任务。
- **执行失败例**：编辑 host-capabilities ledger、伪造 prompt observation，或把新 lane
  绑定到旧 authority 只为让状态变绿。
- **建议路由**：anti-patterns / observability；由协调端判重，当前不自动创建新 task。

### 候选四：exact maintenance grant 不能因命令包装漂移退化成 unknown allow

- **问题类型**：authority bypass / command normalization。
- **语境**：高风险 enforce 合同已为官方 installer 生成一次性 typed grant，但执行命令
  额外携带 no-bytecode 环境和 Python `-B`。
- **证据状态**：verified。seq 813/814 的同一 call 被记录为 `effect=unknown`、无 profile、
  无 continuation authority，决策仍为 allow；r8 continuation use 只有 cachebuster，
  installer grant 未消费。
- **路由正例**：在 grant 构造时密封允许的解释器选项/环境，或把 wrapper 规范化进同一
  typed binding；匹配成功才执行并形成 effect attempt/独立验证。
- **路由反例**：精确 profile 不匹配后回落到 unknown degraded-allow，尤其是合同已经声明
  high risk 和外部写入时。
- **执行合格例**：变体不在密封集合则执行前 deny/ask；已经发生的动作只记录事实与独立
  后置证明，不重放、不补造 grant consumption。
- **执行失败例**：为让账本变绿重复安装、直接改 continuation uses，或把 OS sandbox Allow
  冒充 Guardian typed authority。
- **建议路由**：anti-patterns / authority；新修复批次必须覆盖 interpreter wrapper、
  scheduler/bootstrap typed profile 与 unknown fail-closed 回归。
- **revision 9 结果**：源码正例、反例与一次性消费均已由 199/199 scoped 和 1446 项
  clean-clone 套件（1440 pass、6 skip、exit 0）验证；生产发布证据仍待下一张精确绑定卡，
  不把源码通过冒充 live 完成。

### 候选五：注册 verifier 的 proof 成功不等于效果事务已闭环

- **问题类型**：control-plane capability routing / verification gap。
- **语境**：scheduler 已真实完成，注册 verifier 在可信宿主返回精确 proof，但公开恢复入口
  仍保持 `reconciled_count=0`。
- **根因**：终态 matcher 维护了独立的 machine-verifier allowlist，遗漏 scheduler 与
  launcher capability；proof 在进入 `verify_from_read` 后被拒绝。
- **证据状态**：verified。revision 19 定向 2/2、`test_intervention.py` 69/69、Intent
  Guardian 193/193、clean clone 1449 项（1443 pass、6 skip、exit 0）。
- **路由正例**：测试完整的 typed effect → `verifying` → exact registered verifier → 唯一
  `system_verified` 事务，并拒绝普通 read、缺失能力和任意别名。
- **路由反例**：只调用 verifier 函数并断言返回 proof，就把恢复链宣称为可用。
- **建议路由**：并入 verify-build 端到端验证条目；消费者包括 EffectRouter、intervention
  matcher、safe-host reconciliation CLI 与发布验收。

### 候选六：live 验收重启不应依赖尚未 applied 的 proposal

- **问题类型**：workflow / continuation authority boundary。
- **语境**：生产 effect 已全部执行和结算，唯一剩余步骤是重启当前宿主并取得新的真实
  SessionStart；当前 revision 已 applied，因此不存在 current proposal。
- **根因**：`prepare-continuation` 把“存在 current proposal”作为统一前置条件，无法表达
  applied revision 下仅恢复同一原生 session 的 live-verification 阶段。
- **证据状态**：verified。命令在零状态变化下拒绝；Codex 原生 exact-session resume 后，
  当前 runtime 生成新 SessionStart/UserPromptSubmit，最终 doctor 全部 ready。
- **路由正例**：恢复同一 native session，重新建立 freshness evidence，不迁移或扩大 authority。
- **路由反例**：仅为生成 capsule 创建虚假 revision，或把旧 approval 转移到新 session/lane。
- **建议路由**：continuation / host-adapter；区分 proposal continuation 与 post-apply live resume。

### 候选七：legacy deployment 标签不能覆盖权威 readiness gates

- **问题类型**：observability projection mismatch。
- **语境**：同一 doctor 中 artifact、scheduler、pairing、effect、interactive 与 operational
  全部 ready，但 `deployment_status` 仍显示 `installed_live_unverified`。
- **证据状态**：inconclusive。已证明标签与权威 gate 不一致，尚未确定它是兼容字段、延迟
  projection 还是遗漏迁移。
- **路由正例**：发布决定以明确的权威 gates 为准，同时保留冲突字段用于后续确定性复现。
- **路由反例**：直接编辑 projection/ledger 让标签变绿，或反过来忽略全部 live evidence。
- **建议路由**：observability / projection；单独判重，不纳入当前 G6 修复范围。
