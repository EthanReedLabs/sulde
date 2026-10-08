# Guardian Runtime Control Plane G0-G6 总纲验收

## 总体结论

G0-G5 的源码实现与集成验证已完成；G6 的源码 blocker、typed authority、生产安装、
scheduler/launcher 和 Codex live 均已闭环。`dev@870c5e73ed97fe7b5fd602e9a932815f709c2b8c`
的独立 clean-clone 官方套件总计 1449 项，其中 1443 pass、6 skip、exit 0，运行前后
clean 且无 bytecode。G0-G6 因此进入 **Codex-hosted release accepted** 状态。

真实 Claude live 仍未验证，当前额度也不可用。用户已明确把该证据从 G6 Codex 发布硬门禁
调整为 R2 的独立进入条件：双宿主静态契约继续通过，但在真实 Claude
SessionStart/UserPrompt/tool boundary 证据出现前，不宣称 Claude production accepted，
也不允许 synthetic callback 或另一宿主观察替代。该调整改变的是发布分层，不改变任何
历史证据或 fail-closed 规则。

## 分阶段验收

| 阶段 | 交付 | 验收 | 状态 |
|---|---|---|---|
| G0 | 跨 revision effect subject、read debt、worktree/0400-0644 止血 | 定向与隔离失败组通过；不放宽外部效果边界 | accepted |
| G1 | 强类型 Event Envelope 与唯一纯 reducer | replay、terminal、epoch、generation 不变量通过 | accepted |
| G2 | registry-first EffectRouter 与 typed verifier | read/write 能力、legacy fallback、verifier 精确匹配通过 | accepted |
| G3 | bounded inbox、单写者 supervisor、lease/generation fence | backpressure、幂等 drain、crash recovery 与 writer fencing 通过 | accepted |
| G4 | 7 源只读 legacy cut 与 cutover gate | production v2 cut 7/7 稳定；actionable pending=0、blockers=0 | accepted |
| G5 | 冻结 TaskEpochContext 与 config/tool/verifier digest | epoch/generation/config 漂移拒绝通过 | accepted |
| G6 | exact release、事务安装、scheduler、Codex live、总纲合并 | 新版 production authority、15/15 scheduler、Codex live 与 1449 项 clean-clone 通过；Claude live 延期为 R2 独立门禁 | accepted_for_codex_hosted_release |

## 已证明的总纲方向

本批次验证了原总纲的核心方向正确：

1. **强类型事件 + 唯一 reducer** 能把 authority、effect、intervention 和 task 终态分离，
   避免字符串状态在模块间漂移。
2. **单写者 + generation fence** 能让 scheduler、launcher、installed artifact 和 host
   observation 对齐到一个不可变 runtime。
3. **冻结 TaskEpochContext** 能阻止旧 revision/session/approval 被新任务消费。
4. **typed EffectRouter** 能把 Figma read 等能力从文本猜测升级为明确 no-effect 语义，
   同时保持未知写入 fail-closed。
5. **只读 legacy cut** 能在不改写历史的前提下暴露真实 blocker，而不会用 migration
   伪造 authority。

G6 新 finding 也证明下一步必须继续沿用同一方向：仅有多个“各自正确”的 writer 仍不够；
launcher manifest 与 scheduler seal 共享 projection 时，必须由统一 schema/reducer 或原子
composition 管理，否则 launcher refresh 会覆盖 scheduler 字段。

## 发布基线与证据

- G6 source fix：`620e71aa19df1b11806c9a74f06e115df7fe322d`。
- source evidence：`55026bee30537ba8b6787596a17fa81d1ea45671`。
- cachebuster/release head：`ad8d303d252746c672782fa96571db11908987eb`。
- r9 typed maintenance source head：`0276a02324470b140300c40e710b0f3901e6ed60`。
- 当前 production plugin version：`0.2.5+codex.20260825160039-6485efd444`。
- installer operational result：revision 20 的 v2 no-bytecode cachebuster/install grants
  各唯一消费并独立 `system_verified`；revision 21 的 scheduler/launcher grants 同样唯一
  消费并闭环，最终 effect truth 12/12 `system_verified`。
- 当前 dev clean-clone official suite：总计 1449 项（1443 pass、6 skip）、exit 0；运行
  前后无 bytecode 与工作树变化。
- revision 9 Intent Guardian scoped：199/199 通过。
- G0-G5/核心定向：307/307 通过。
- installed generation：`0.2.5+codex.20260825160039-6485efd444:dc083caec0982ecc0d97eda6b1c9b6cf0b3bf687c4c79ba09325c6f0e95b1bef`。
- scheduler：15/15 ready，missing/failed/retired 为 0。
- launcher-only production regression：runner path/digest seal 保留，owner/generation/tree 一致。
- 新 Codex session：当前 generation 的 SessionStart/UserPrompt/PreToolUse/PostToolUse/Stop
  live evidence 存在，返回 `G6_CODEX_COMBINED_CANARY_OK`；lane 正确
  `review_required`，无旧 authority 继承。
- Claude：静态兼容已测；无活跃宿主，live 未验证。
- legacy v2 cut：7/7 sources，pending native transaction 0，历史诊断 5，blockers 0。

## 已关闭的原 blocker

### B-G6-001：旧版 unsealed prepared transactions

已用 exact predicate 把无 seal、无 operation、无 terminal/authority 且事务摘要自洽的
旧版 prepared 行只读分类为历史诊断；其他形态仍 actionable/fail-closed。production v2
cut 已证明 pending=0、historical=5、blockers=0。没有 append 虚假 supersede、删除 JSONL
或修改 projection 计数。

### B-G6-002：launcher refresh 与 scheduler seal 组合缺陷

源码已增加同 provider/platform/generation/runtime root/tree/owner 的严格组合验证；只有
官方 runner 是 KB `bin` 下非 symlink regular file 且摘要匹配时才保留 seal。回归和
production journey 已覆盖：

- 先安装 scheduler seal；
- 再执行 launcher-only refresh/bytecode repair；
- manifest 仍包含 exact runner path/digest，或 refresh 原子触发同 generation reseal；
- 15/15 jobs 不出现 exit 1；
- 非 bytecode drift 仍拒绝 repair。

真实 launcher-only refresh 后 seal 仍存在，15/15 jobs 保持 ready；任一 drift 仍省略
extension 并 fail-closed。该项已关闭，没有暗中创建 G7。

## 延期项与严格边界

### B-G6-003：Claude live 证据缺失

当前没有可用额度支持真实 Claude 宿主验收。只有在真实 Claude
SessionStart/UserPrompt/tool boundary 与 installed generation 对齐后，才能把 Claude
production acceptance 标记为通过；synthetic hook、source test 或另一宿主观察都不能
替代。该项状态为 `deferred_r2_gate`，不再阻断 Codex-hosted G6 发布。

### B-G6-004：installer typed authority 已闭环

r8 已生成一次性 `codex-plugin-install-v1` grant，但实际命令额外带
`PYTHONDONTWRITEBYTECODE=1` 和 Python `-B`，未进入 typed profile。seq 813/814 明确记录
为 `effect=unknown`、无 continuation authority，却在 enforce 模式被 degraded-allow。
安装器本身已由官方事务后置证明验证，当前生产 generation 不需回滚；但不得把成功结果
倒推出 authority。

revision 20/21 已用新发布 generation 真实消费 v2 no-bytecode cachebuster/install 与
scheduler/launcher grants；四类动作均由独立 verifier 形成唯一 `system_verified` 终态，
pending/open intervention 为零。该项为 `fixed_current`，不再是生产 blocker。

## 运行态与发布态的区别

- **运行态**：当前 Codex installed generation 已安装，scheduler 与 Codex live canary
  已通过；权威 doctor 为 `operational_status=ready`。
- **发布态**：G6 对 Codex-hosted release 已 accepted；报告收口提交通过最终 release gate
  后可按 task → `dev` → `main` 快进。Claude live 保留为 R2 独立门禁。

这种区分避免两个常见误判：一是把其他历史 workspace 的全局 warning 当成当前会话不可用；
二是把 Codex 当前会话 ready 反推为 Claude 宿主也已完成 live 验收。

## 控制面收口记录

- 所有新发现均被分类为 `fixed_current`、`observed_nonblocking` 或
  `deferred_r2_gate`；没有为了刷绿自动增加 G7。
- 生产 active JSON/JSONL/effect ledger 未被编辑、删除、重排。
- 已密封历史事务只消费既有 durable authority 和独立后置证据；原外部操作未重试。
- 首个损坏期 Codex session 未冒充 canary，未配对的 native Allow 未冒充 receipt。
- 0400/0644 mode drift 已排除，不作为摘要不一致的替罪解释。
- G6 源码 task 已到达 `dev@870c5e73`；本次报告收口仍禁止 push，并以受管 Git refs 回读
  证明 task → `dev` → `main` 的本地快进结果。

## R2 的最小进入条件

G0-G6 的 Codex-hosted release 收口后，R2 才可单独启动。其首个未完成门禁是：在额度可用的
真实 Claude 宿主中执行当前 installed generation 的 SessionStart/UserPrompt/tool boundary
live canary，并独立回读同一 generation；通过前保持 `deferred_r2_gate`。R2 不得重复
cachebuster、installer 或 scheduler 来“制造”该证据，也不得删除历史、复用 receipt、放宽
fail-closed 或让 synthetic callback 冒充真实宿主。
