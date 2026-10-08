---
scheme_id: SULDE-R2-HALG-20260825
title: Sulde R2 Human Authority & Lifeform Governor
status: READY
capability_tier: deep
created_at: 2026-08-26
repository: /Users/eric/ClaudePlugin/sulde-cc-pro
source_program: guardian-p0-supervised-delegation-20260815
source_acceptance: guardian-program/reports/program-final-acceptance-t32.md
parked_source_path: .ai-workspace/handoff/SULDE-R2-HALG-20260825.md
parked_source_sha256: 3c648a1904cde11ee05f289d0168601a709da104158fd8b4104129d6061f6046
canonical_path: guardian-r2-program/briefs/SULDE-R2-HALG-20260825.md
branch_base: dev@0eb4fb6553e652b0352750f4bac24aa6bae746d7
branch: task/r2-guardian-human-authority-lifeform
worktree: .worktrees/guardian-human-authority-lifeform
promotion_receipt: guardian-r2-program/promotion-receipt.json
---

# SULDE R2 方案罗盘：Human Authority & Lifeform Governor

## 0. 文件身份与激活状态

这是 R2 从停车文件提升后的 tracked 单一事实源。原停车文件保持只读，摘要固定为
`3c648a1904cde11ee05f289d0168601a709da104158fd8b4104129d6061f6046`；本文件及
`promotion-receipt.json` 接管后，不再从聊天记录或停车文件重建第二份计划。

`READY` 表示启动门已经独立回读通过，只允许从 H00 开始按依赖执行；不代表产品源码、
安装或发布已完成：

- [x] 旧 Guardian Program final-check ready，108 evidence 零错误，78 findings 全处置。
- [x] main、dev 与 13 个历史 task worktree 独立回读均干净。
- [x] 从 `dev@0eb4fb6` 通过 `agent-runtime.py provision` 创建隔离 task worktree。
- [x] 当前会话原生 Allow 已形成 revision 152 receipt；安装、推送、合并和生产写仍禁止。
- [x] 停车文件摘要与提升 receipt 已记录。
- [x] I01-I19、宿主/runtime 与测试基线完成 tracked freeze。
- [x] H00-H06 的依赖、owned paths、failure injection 和 reviewer 完成 append-only 注册。

快速定位：

```bash
rg -n "SULDE-R2-HALG-20260825|HumanGrantV2|RecoverySupervisor" \
  guardian-r2-program
```

## 1. 为什么需要 R2

G0-G6/T32 已解决强类型事件、单写者、generation fence、旧账本投影、native transaction
兼容和 release 验收等基础问题，但 19 组真实操作暴露了同一个上层缺口：系统能判定
“风险”，却不能稳定地把人的明确决定转化为可消费、可恢复、可验收的执行权威；生命体
也没有成为卡顿、锁冲突、自锁和宿主失配的主动恢复所有者。

当前失败通常来自六种混淆：

1. 把硬安全不变量、默认策略、任务范围、宿主权限和运行时健康混成同一个 deny。
2. 人工 Allow 与实际 effect dispatch 分属两套状态机，中间可被 PreToolUse 再次拦截。
3. task lane、proposal CAS、历史 replay 债务会遮蔽刚生成的当前会话权威。
4. Git/Figma/设备/跨项目/精确删除缺少资源级身份，守卫只能按字符串过度拒绝。
5. 锁、worker、scheduler 和 runtime drift 没有独立 liveness owner，只会等待或让人抄命令。
6. 恢复入口和普通工具共用同一个守卫，导致“修复守卫的命令也被守卫拦截”。

R2 的核心不是放松所有限制，而是把授权、资源、效果和恢复做成精确的强类型协议：常规
操作减少拦截；高影响操作仍由人决定；一旦人对精确动作明确 Allow，执行链必须消费该权威
或给出可见的世界状态变化理由，不能再次用同一条策略拒绝。

## 2. 目标与不可退让边界

### 2.1 目标

- 人工 Allow 生成 `HumanGrantV2`，成为 EffectRouter 可直接消费的一次性权威。
- 对精确 Git、跨项目、删除、Figma、设备和 handoff 写入建立资源级 capability。
- 建立独立 `RecoveryLane`，恢复 UI、状态查询和受限修复永远不被普通 task deny 自锁。
- 让 `RecoverySupervisor` 主动处理无进展、死锁、孤儿锁、worker 退出和 runtime drift。
- 对可逆、已知、局部的常规操作自动放行；只把真正的人类决策留给人。
- 所有等待都有状态、所有授权都有终态、所有恢复都有独立证据，减少重试与 token 浪费。

### 2.2 不可退让边界

- Agent 不能伪造或替代人的决定；文本“批准”不能冒充原生 PermissionRequest receipt。
- 人工授权必须绑定 provider、session、task epoch、资源身份、effect、约束和有效期。
- 不允许把目标不明、资源身份漂移、receipt 篡改或未验证外部效果自动当成功。
- 不通过 shadow/off、手改 active JSON、复制 digest 或外部终端命令绕过正常控制面。
- 精确破坏性动作可以由人授权，但授权不能扩张到父目录、相邻资源或后续不同动作。
- 生命体只能使用密封的恢复 capability；不能借“自愈”获得通用业务写入权。

### 2.3 权威优先级

```text
不可伪造的不变量（身份、完整性、单次消费、目标绑定）
  > 当前 HumanGrantV2 的精确决定
  > 已密封的系统/Agent capability
  > 工作区和工具的默认策略
  > 启发式风险判断
```

人的精确 Allow 可以覆盖默认的 Git、跨项目、`.git`、删除或外部写入策略，但不能覆盖
“无法确定操作对象”“receipt 不属于当前会话”“授权已被消费”“目标已发生实质漂移”等
完整性事实。发生实质漂移时只能展示差异并请求一次新决定，不能静默重试。

## 3. PARKED → READY 启动门

只有同时满足以下条件才允许从 `PARKED` 转成 `READY`：

1. 现有 Guardian Program 的 task graph 无 `running/blocked/open finding`，accepted evidence
   已通过独立回读；不得仅引用本文件中的历史描述。
2. `dev`、`main` 和现有 task worktree 状态已只读核对；不在 `main` 直接实施。
3. 从 `dev` 创建仓库内 `.worktrees/guardian-human-authority-lifeform` 和独立 task branch。
4. 把停车文件提升为该 worktree 内的 tracked plan/brief，并记录源文件摘要和提升 receipt。
5. 冻结 19 组 incident fixtures、宿主版本、runtime generation 和基线测试结果。
6. 建立 H00-H06 任务图、依赖、allowed paths、failure injection 和独立 reviewer。
7. 展示一次新任务原生 Allow/Deny 卡；Allow 前不得写源码、安装或修改生产账本。

任一门后来发生实质漂移，状态回到 blocked finding，只输出差异和下一步，不重建方案。

## 4. 目标架构

```text
Codex / Claude / UI adapters
           │
           ▼
      GrantBroker ───────────────► HumanGrantV2 ledger
           │                               │
           ▼                               ▼
   AuthorizationReducer ───────────► EffectRouter
           │                               │
           ▼                               ▼
      RecoveryLane ◄────────────── Effect receipt / verifier
           │
           ▼
   RecoverySupervisor ──► managed actors / locks / scheduler / runtime repair
```

GrantBroker 不执行业务效果；EffectRouter 不解释自然语言授权；RecoverySupervisor 不扩大
任务目标；各宿主 adapter 只做协议转换，不持有第二套权威真相。

## 5. 实施波次

### R2-0 — HumanGrantV2 与风险校准

交付宿主中立、可序列化、单次消费的授权对象：

```text
HumanGrantV2 {
  grant_id, provider, session_id, task_epoch,
  subject_resource_id, capability, effect,
  exact_constraints, card_sha256, request_id, receipt_id,
  issued_at, expires_at, world_state_sha256,
  consumption_state, verification_requirement
}
```

- 风险分为 read、reversible_local、external_or_destructive、integrity_unknown 四层。
- 已知 read 始终可用；可逆局部写按 task capability 自动决断；高影响精确动作走原生卡。
- HumanGrantV2 生成后，普通策略不得对同一 effect 再次否决。
- 只有资源/world-state 实质漂移才能中止消费，并必须展示可读 diff。
- 同一 grant 只能消费一次；retry/reprobe 使用派生、次数受限的恢复 grant。
- 宿主长会话不要求 Hook 热加载才能配对授权；broker 持有可热更新协议版本。

### R2-1 — 原生授权事务与自锁隔离

```text
card_ready → permission_pending → granted|denied
granted → dispatching → effect_observed → verified → settled
                    ↘ recovery_required → retry|reprobe|abort → settled
```

- PermissionRequest 展示通道先于普通 PreToolUse，task pause/deny 不能阻止卡片出现。
- grant、dispatch intent、effect receipt 和 verifier 通过同一 transaction/outbox 串联。
- crash 后按 transaction id 幂等推进，不重放人类决定和外部效果。
- 不再要求“批准当前方案”“继续”或复制 shell/digest 作为权威 fallback。
- 无原生桥接的宿主必须提供等价 UI decision adapter；不可退回固定文字。
- break-glass 仅供控制面完全不可用时的人类独立通道，正常恢复不依赖它。

### R2-2 — RecoverySupervisor（生命体）

生命体持续观察 task/worker 心跳、进度游标、锁与 lease、进程、worktree/resource ownership、
GrantBroker/Hook/ledger/scheduler/runtime generation、一致性、卡片展示、授权消费、effect 回证
和并行 allowed-path 冲突。

允许的主动干预：

- owner 已死且 lease 到期时自动回收孤儿锁，并追加 recovery receipt；
- 并行写冲突时暂停最小 lane、保留双方状态、重新排队，不停掉整个 program；
- managed actor 退出时按退避和次数预算重启，超限后显示终态卡；
- native 卡未展示时切换到独立 broker 展示通道，不通过普通工具探针触发；
- generated bytecode/runtime drift 使用密封 safe-repair capability；
- 历史债务只阻断关联 subject，不把无关读写升级成全局 deny；
- 5 秒内显示发生了什么、系统做了什么、还需人决定什么和下一步选项。

禁止无限重试、静默切 provider、终止健康会话、擅自合并冲突改动、扩大 allowed paths、
把 timeout 当授权、在无 verifier 时宣称恢复成功。

### R2-3 — 资源与宿主适配器

#### Git / worktree

- 解析 worktree 实际 gitdir，把 `.git/worktrees/<id>` 作为 `GitMetadataResource`。
- 人批准精确 `git add/commit/merge` 后授予 metadata capability，不再永久拒绝 `.git`。
- 保持 main release-only、pathspec allowlist、无 amend/rebase/越界写等仓库规则。
- Git read、status、diff、rev-parse 不因跨项目或 task lane degraded 被阻断。

#### 文件系统与精确删除

- 删除 grant 绑定 canonical path、device/inode、对象类型、尺寸/文件数快照和父目录边界。
- 已批准的失败发布包或临时 clone 可机械删除并独立 `test ! -e` 验证。
- 不使用“出现 rm 就永久拒绝”的字符串策略；目标漂移时停止并展示差异。

#### 跨项目

- `WorkspaceResource` 使用 canonical root + repository identity；人的精确授权可新增一个
  有效期和 capability 均受限的协作 workspace，不改变主工作区归属。
- 跨项目 grant 不可被其他 session、repo 或后续不同任务继承。

#### Figma / MCP

- Figma 写入资源至少包含 `fileKey + nodeId/page + mutation kind + expected readback`。
- `use_figma`、`apply_patch` 和其他 adapter 必须提取真实目标，禁止空 target/unknown effect
  把已隔离历史债务变成全局阻断。
- 写后以 node 结构、截图或指定属性回读验证；权限不足与 Guardian 拒绝分开报告。

#### 设备

- 绑定 device serial、package/bundle、安装/启动/测试数据 capability 和保留条件。
- 覆盖安装、清数据、购买、删除原数据是不同 capability，不能互相隐式包含。
- 设备只读探测不因旧授权 replay 故障被统一拒绝。

#### Skill、runtime 与安装器

- Skill start/end 审计写入本地 spool/服务；锁或旧批准迁移失败降级告警，不阻断 Skill。
- immutable runtime digest 排除生成 bytecode，或强制 `PYTHONDONTWRITEBYTECODE=1`；官方
  launcher repair/uninstall/status 通过 RecoveryLane 永远可达。
- 报告拆分 `registered_path_verified`、`descriptor_version_verified`、
  `reported_version_matches`，避免 `plugin_list_verified` 语义混淆。

### R2-4 — RecoveryLane、状态卡与输出预算

```text
inspect_status | show_pending_decision | settle_transaction |
release_stale_lock | restart_managed_actor | repair_generated_bytecode |
rebind_exact_resource | abort_related_effect | uninstall_or_rollback
```

- task 为 paused/review_required/unavailable 时，RecoveryLane 仍可执行只读和密封修复。
- 恢复动作不先经过会阻断它的普通 PreToolUse；只由 recovery capability gate 校验。
- UI 卡有 `Allow / Deny / 查看差异 / 稍后`，无需人工输入固定短语。
- 进度等待以一张可更新状态卡呈现，不重复输出 `Waiting for agents`。
- 5 秒内首次状态，最长 30 秒一次进度；超预算自动显示超时原因和三种下一步。
- stdout 默认折叠为阶段、进度、终态摘要；完整日志落本地证据文件。
- Stop、status、doctor、uninstall、repair 和只读诊断不能被 launcher/runtime 自锁循环阻断。

### R2-5 — 19 组事件回放、故障注入与发布验收

真实事件矩阵的机器可读冻结位于 `guardian-r2-program/fixtures/incidents.json`。除 I01-I19
外还必须覆盖双宿主真实版本、macOS/Windows、并发冲突、进程死亡每个事务阶段、receipt
tamper、world-state drift、UI 不展示、账本只读、scheduler degraded、rollback 和重复
callback。外部平台内容安全限制必须准确分类，不能伪装成权限或 workspace 问题。

## 6. 冻结任务图

```text
H00 冻结 19 组 fixture 与基线
 └─ H01 HumanGrantV2 / risk taxonomy
     └─ H02 GrantBroker / native transaction
         ├─ H03 RecoverySupervisor / locks / actors
         ├─ H04 Git-FS-Workspace-Figma-Device adapters
         └─ H05 RecoveryLane / UI / progress budget
             └─ H06 fault injection / live hosts / release acceptance
```

- H00/H01 是所有后续任务的协议前置。
- H03/H04/H05 在 H02 后可并行，但 owned paths 不重叠。
- H06 只接受集成后的 exact commit 和安装制品，不接受 worker 自报成功。
- 独立 reviewer 固定为 `guardian-r2-independent-reviewer`；任何 finding 必须入账并关闭。

## 7. 硬验收指标

1. 精确 Allow 到 dispatch/可读阻断终态 P95 ≤ 3 秒；同一策略二次 deny 为 0。
2. PermissionRequest 展示前被 task/tool guard 拦截为 0；固定文字授权为 0。
3. Guardian degraded 时 read/status/doctor/recovery availability 为 100%。
4. owner 已死且 lease 到期后，孤儿锁在 10 秒内回收并有 receipt。
5. managed actor 静默 5 秒内出现状态，30 秒内持续进度，超预算自动终态化。
6. 精确 Git commit、跨项目写、精确删除、Figma 写、设备覆盖安装各完成 live PASS。
7. `.git` 不再永久硬拒绝；仍有 repo/worktree/pathspec/branch 策略和 verifier。
8. runtime 生成 bytecode 不改变 sealed digest；repair/uninstall/status 不自锁。
9. 历史债务只阻断同 subject；19 组 fixture 无全局级联 deny。
10. crash/retry 不重复 PermissionRequest、Git push、设备写、Figma mutation 或删除。
11. 并行冲突不丢改动、不产生双写者、不要求人先猜状态；恢复卡说明下一步。
12. 重复 `Waiting for agents` 输出为 0；完整日志可追溯，默认摘要不制造 token 洪峰。
13. Codex 与 Claude Code 各有最新版真实宿主闭环；Windows 有真实或受控硬件证据。
14. isolated full suite、failure injection、历史 replay、installer rollback、live canary 全绿。

## 8. Codex-first / Claude-deferred 执行边界

当前 provider 为 Codex，capability tier 为 `deep`。H00-H05 和 H06 的 Codex 源码、fixture、
fault-injection 与本地集成可继续；不得调用 Claude 或用 synthetic callback 冒充 Claude live。
在真实 Claude SessionStart/UserPrompt/tool boundary 对齐同一 installed generation 前，H06
只能到 `Codex accepted / Claude live deferred`，R2 program 不得 complete、安装或发布。

## 9. 完成定义

R2 只有在 H00-H06 全部 accepted、19 组真实事件闭环、硬指标满足、双宿主和安装态通过、
rollback 可用且独立 reviewer 无 open finding 后才完成。源码测试通过但 live grant 消费、
RecoveryLane 或生命体干预未通过时，必须判为未完成。

## 10. 沉淀候选

- **问题语境**：显式人类授权与 effect dispatch 分裂，使同一动作在 Allow 后再次被默认策略
  拒绝，并把恢复入口置于被恢复对象之后。
- **证据状态**：confirmed；I01、I08、I10、I12、I13、I16、I18、I19 有重复真实 transcript。
- **正确路由样本**：原生卡 → HumanGrantV2 → EffectRouter 单次消费 → verifier → settled。
- **错误路由样本**：文本批准、复制 digest、外部终端修复、切 shadow、无限 waiting/retry。
- **执行正样本**：资源身份精确、world-state CAS、恢复 lane 独立、生命体限权干预、终态可见。
- **执行反样本**：`.git`/`rm`/跨项目永久硬拒绝、空 MCP target、pyc 漂移导致 repair 自锁、
  无关历史债务全局阻断。

证据足够时由协调端按单写者规则判重沉淀；本文件不直接写知识库。
