# A：隔离候选消费者补接

状态：候选待独立复核；未安装、推送或自行 accepted。

## 根因与范围

本候选将 POSIX Hook 注册改为缓存外稳定命令，但隔离候选 verify 及八个
真实本地宿主夹具仍只调用 `_registry_add → _install_launchers → smoke`。
其中 `_install_launchers` 不负责发布 `bin/sulde-codex-hook`；原缓存 wrapper
不需要该文件。因此这是本候选迁移遗漏，不是旧 dev 的 string-flow 分类缺陷。

同一 `GuardianStringFlowNativeTests.test_real_candidate_business_shapes_and_retained_pre_denial`
在补接前实际失败（12.160 秒）：finalize 报
`pre-execution probe lacks one live exact PreToolUse denial`。
稳定注册层对缺入口仍 fail-closed，但该传输层拒绝不能代替 Guardian 账本中的
精确 live Pre 证据；finalize 因而正确拒绝，不应放宽终验断言。
补接后同原断言通过（15.857 秒），真实 app-server/unified_exec 返回业务正例成功、
字符串转换成功、破坏性路径替换被 Pre 拒绝及完整代际事件身份；模型外部请求为 0。
最初受限运行的 loopback bind PermissionError 是宿主沙盒限制，不混入代码根因。

## 最小改动

在既有 candidate 模块新增共享 `_prepare_isolated_hook_launchers`。首次写入前
校验 candidate 的 `isolated/sulde-home`、KB、Codex cache、HOME、launcher home、
LaunchAgents 实际路径与活动进程环境一致；拒绝 symlink、误指目标、非隔离 cache。
然后安装原 launcher，对已声明 stable 协议的 POSIX 候选复用 entry 的
prepare/publish/verify，并绑定已有 isolated runtime interpreter。
生产 `_install_launchers`、正式事务时序、模板与授权策略未改变。

统一消费者：

- `scripts/release/candidate_codex_plugin.py` 的 verify。
- `tests/test_native_pretool_delivery.py`。
- `tests/test_native_memory_continuation.py`。
- `tests/test_historical_retirement.py`。
- `tests/test_repository_relocation.py`。
- `tests/test_native_session_continuity.py`。
- `tests/test_guardian_string_flow.py`。
- `tests/test_native_control_composition.py`。
- `tests/test_native_memory_consistency.py`。

## 验证

- candidate 模块 21 项通过（15.655 秒）。新正常例实际发布并验证稳定包，
  新边界负例确认误指目标时 launcher/entry 均零调用、哨兵目录无写入。
- 补充活动环境与传入映射不一致反例通过（0.063 秒）。
- 原失败 string-flow 本地真实宿主单项通过（15.857 秒）。
- 其余七个受影响 native 消费者共 14 项全部通过（278.563 秒）：pretool、
  memory continuation、historical retirement、repository relocation、session
  continuity、control composition、memory consistency。包含 Allow/Deny、
  实际工具正反例、会话隔离、Post 丢失恢复与连续十次记忆登记。
- 合计真实本地宿主用例 15 项全过，候选模块 21 项全过；未放宽原有断言。

新单测首跑曾误写模板复制路径（多写 hooks 子目录），导致 FileNotFoundError；
修正夹具路径后通过，不归因为生产缺陷。证据位于子会话工具输出，协调端统一归档。

## 未验收

本地 NativeCanary 使用确定性 loopback 提供方；真实宿主链成立不代表真实付费
Agent 能力验收。未运行生产安装、真实 native 人工审批或生产恢复事务。
最终集成全量及生产边界由协调端验收。

## 首次写入子目录边界补充

独立复核发现 56356ab 只检查 home 等根目录，未检查实际写入父目录 `home/bin`。
若 bin 链接到临时隔离区外目录，旧 launcher writer 会沿链接写入，后续 entry
校验才拒绝已经太迟。该问题属于本候选 helper 的校验遗漏，原记录保留。

首次 writer 前新增 bin/hook-entry 的 lstat 检查：拒绝链接（含 dangling）、
非目录、非 canonical 路径、非当前所有者及 group/other 可写目录。
缺失目录仍允许由原实现创建。未改生产 `_install_launchers`；其 leaf 文件通过
mkstemp+replace 原子替换，不沿 leaf symlink 写，故没有另建逐文件写入机制。

八场景反例先在 56356ab 全红（0.063 秒），其中 bin 链接确实让替身 writer
在临时生产替身目录创建 marker；无真实生产操作。同一测试修后八场景全绿，
断言原 writer/entry.prepare 均未调用、外部目录零变化、拒绝对象原样保留。
配对正常例使用已有 0700 bin/hook-entry 并成功发布；两项共 0.082 秒。
最终 candidate 模块 22/22 通过（15.673 秒），diff --check 通过。
此前 15 项宿主结果仍对应前轮树，本次窄守卫变更不冒充已重跑该批。
