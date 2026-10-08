# H02 GrantBroker repair2 验收报告

## 结论

repair2 修复 FR2-H02-004：broker 先对已存在 contract 做 strict canonical
identity 解析，再逐级 no-follow 打开 canonical parent，并把 parent 的 pathname
identity 与后续所有 `dir_fd` 操作使用的 descriptor 绑定；只有绑定成功后才派生
ledger/lock 叶名。`/var/folders/...` 与 `/private/var/folders/...` 因而选择同一
ledger、lock 和 transaction projection。repair1 的 FR2-H02-001、FR2-H02-002、
FR2-H02-003 修复全部保留，winner-only executable dispatch 与 public/native
redaction 未改变。

冻结基线仍为 `0eb4fb6553e652b0352750f4bac24aa6bae746d7`。H01 依赖
`scripts/kb/human_grant.py` 的 SHA-256 仍为
`6b5ec257cb4ca0edb446f861aab1aea19f43bec17ff6711804bcb7ecbc0cb2d8`。

## Findings 与修复

| Finding | 修复与证据 |
|---|---|
| FR2-H02-001 | ledger 末尾缺少换行继续统一表述为 `torn trailing record`；replay 仍然阻断，不截断、不猜测恢复。 |
| FR2-H02-002 | durable journal 内部继续保留 canonical dispatch 供验链；只有首次 atomic claim 的 winner 收到 `execution_authorized=true`，retry、loser 及所有 readback 只得到不可执行投影。 |
| FR2-H02-003 | ledger/lock 叶仍以 `dir_fd`、no-follow、CLOEXEC 打开；普通文件、owner、mode、hard-link count 与 fd/path device+inode 校验未放宽。 |
| FR2-H02-004 | 独立复现的 lexical `/var/folders` parent walk 会在系统 `/var` symlink 处报 `NotADirectoryError component=var`。repair2 只 canonicalize 已存在 contract/parent；canonical parent descriptor 与 pathname 的 device+inode 一致后才派生敏感叶名。 |

## Canonical parent 与 leaf 安全边界

- 允许 canonicalize 的对象仅为调用方给出的、已经存在的 contract，以及由它得到的
  canonical parent identity。
- canonical parent 必须绝对、已存在且为目录；root 起点逐级 no-follow 打开后，
  `fstat(parent_fd)` 必须与 canonical pathname 的不跟随 `stat` identity 相同。
- contract 也通过该 parent descriptor 做不跟随 identity 复核，避免 canonicalization
  与 leaf 操作之间静默换父目录。
- ledger/lock 名称在 parent descriptor 绑定后才由 canonical contract basename 派生；
  两个敏感叶从未调用 `resolve()`，也不接受任意 symlink leaf。
- ledger/lock symlink、hardlink、非普通对象、宽 mode、wrong owner、fd/path replacement、
  read-only append 与 torn trailing record 仍 fail closed；不会 chmod、truncate、unlink、
  replace 或改写 foreign target bytes。

## Dispatch replay observable contract

- winner：`status=claimed`，恰好一次收到完整
  `sulde-grant-broker-dispatch-intent-v1` 与 `execution_authorized=true`。
- same-consumer retry：`status=already_claimed`，只含
  `dispatch_reprobe.execution_authorized=false`。
- losing consumer：`status=lost_race`，不含完整 dispatch/effect/authority material。
- durable append 后 retry 仍不可执行；`transaction`、`pending`、
  `load_projection_read_only`、native adapter 与 `next_step` 不泄露执行凭据。

## Commands and observed counts

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_grant_broker -v`
  — exit 0；Ran 12 tests；OK（repair1 11 项加 repair2 1 项）。
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v tests.test_grant_broker.GrantBrokerTests.test_dispatch_claim_replay_and_all_readbacks_are_non_executable tests.test_grant_broker.GrantBrokerTests.test_no_follow_ledger_and_lock_reject_hostile_files_before_write`
  — exit 0；Ran 2 tests；OK；repair1 dispatch replay 与 ledger/lock hostile matrix 均保留。
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_grant_broker tests.test_approval_cas_schema tests.test_approval_timeout_policy tests.test_approval_invariant tests.test_terminal_invariants tests.test_native_decision_journal -v`
  — exit 0；Ran 172 tests；OK；完整 repair1 171 项加 repair2 1 项。
- canonical-alias equivalence probe — exit 0；输出
  `host_lexical=/var/folders host_canonical=/private/var/folders var_is_symlink=True`
  与 `ledger_equal=True lock_equal=True tx_equal=True replay=already_created`。
- `shasum -a 256 scripts/kb/human_grant.py` — exit 0；输出
  `6b5ec257cb4ca0edb446f861aab1aea19f43bec17ff6711804bcb7ecbc0cb2d8`。
- `git diff --check` — exit 0；无 whitespace error。

## 当前宿主限制

当前受管 shell 使用 `/usr/bin/python3` 3.9.6，但 hook 强制把 `TMPDIR` 指向
worktree 内 `.codex-agent/.native-command-scratch`，并拒绝在真实
`/var/folders/.../T` 创建测试临时目录。回归测试在普通 macOS 宿主会直接使用
`getconf DARWIN_USER_TEMP_DIR` 的真实 `/var/folders` 路径；仅在检测到上述受管
scratch 环境且收到 `PermissionError` 时，才在 worktree 临时区构造等价 symlink-parent
拓扑。当前运行同时独立核对了宿主真实 `/var/folders -> /private/var/folders` 映射，
没有把该替代拓扑记录成真实系统目录写入证据。

## Actual changed paths

1. `scripts/kb/grant_broker.py`
2. `scripts/kb/native_decision_journal.py`
3. `scripts/kb/intent_guardian_parts/approvals.py`
4. `tests/test_grant_broker.py`
5. `tests/test_native_decision_journal.py`
6. `guardian-r2-program/reports/H02-grant-broker.md`

## Known limits

- 当前受管 shell 无权执行真实 `/var/folders` 临时写入；普通宿主分支仍需独立运行并
  留存 `actual_system_alias=True` 的证据。该限制不影响当前代码对真实系统 alias 的
  canonical identity 推导，但属于证据环境限制。
- H02 证明本地 durable claim 不会再次签发 executable dispatch；外部 effect 的
  exactly-once 仍依赖 H04 adapter 使用稳定 `dispatch_id` 先 reprobe receipt。
- 完整 ledger 前缀回滚仍需上层独立 head anchor；broker 不自动修复 torn trailing
  record。
- 未触达设备、网络、production state、安装、发布、commit、merge、dev、main 或 H03。

## 沉淀候选

### 问题卡：安全 parent walk 必须区分受信 canonical alias 与敏感派生 leaf

- 问题语境：macOS `/var` 是 root-controlled `/private/var` alias；对 lexical parent
  全路径统一使用 `O_NOFOLLOW` 会把合法系统 alias 当成攻击，在 ledger 操作前失败。
- evidence_status：verified for implementation and equivalent topology；真实系统目录
  写入证据因当前强制 sandbox 为 `inconclusive`，已记录明确复验入口。
- 路由正例：输入包含“macOS `/var/folders`、canonical parent、`dir_fd`、派生 ledger、
  `O_NOFOLLOW`”；应召回本卡。
- 路由反例：输入是派生 ledger/lock symlink 或调用方提供的任意敏感 leaf；不得用
  canonicalization 放宽 leaf policy。
- 执行正例：strict resolve 已存在 contract，descriptor-walk canonical parent，绑定
  fd/path identity 后派生 leaf name；leaf 继续 no-follow 并校验 owner/mode/nlink/inode。
- 执行反例：直接 walk lexical `/var`；或对 ledger/lock leaf 调用 `resolve()` 后打开。

repair1 的 durable one-shot claim 与 pathname leaf-hardening 两张问题卡继续有效，本次
没有改写知识库，由协调端统一判重入库。
