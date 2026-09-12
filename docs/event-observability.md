# Sulde 统一事件契约与观察面

## 目标

Sulde 的 Intent Guardian、L3、自修复、召回、记忆采纳、知识沉淀、Golden 复核和器官
进化分别拥有自己的事实记录。它们的写入频率、生命周期和故障边界不同，因此本设计不把
这些日志迁入一个中央 Event Store，也不要求生产者双写。

统一发生在**读取边界**：每个已声明来源通过适配器投影为
`sulde-observation-event-v1`，CLI、状态灯和周治理消费同一份脱敏契约。

```text
领域 JSONL（仍是事实源）
  ├─ Intent audit
  ├─ host capability observations
  ├─ session continuation lifecycle
  ├─ EffectAttempt / Intervention audit
  ├─ correction intervention lifecycle
  ├─ approval question/decision / managed execution
  ├─ recall / memory adoption
  ├─ sedimentation / golden review
  └─ governance / evolution
             │ 只读适配
             ▼
  sulde-observation-event-v1
             │
       summary / query / verify
             │
       status + governance light
```

`host-capabilities.jsonl` 只证明某个宿主边界被调用，不证明模型理解了上下文，也不证明外部
副作用成功。行内保存 provider、native session、能力、Hook 和 workspace 的哈希标识，不
保存工作区原始路径；`synthetic_smoke` 与 `live_host_hook` 分开投影。外部写入是否成功仍以
EffectAttempt、独立回读和 Intervention 为准，能力观察不得提升权限或解除阻断。
观察还绑定产生它的 Hook/Adapter 内容摘要，插件升级后的旧运行时记录只能作为 stale 诊断，
不能证明当前发布件已被宿主加载。
同一 runtime/session/workspace/Hook/source 只保留一条就绪事实，避免把每次工具调用复制成
第二份审计；完整工具时序仍以 Intent audit 为权威来源。

## 公共信封

每个事件固定包含：

- `event_id`：由逻辑来源、行号和原始行摘要确定性生成；不会复用宿主不稳定的 call id。
- `occurred_at`：必须是带时区的 ISO-8601，并统一投影为 UTC。
- `domain/type/phase/outcome`：跨领域统计口径。
- `provider/actor`：区分 Claude、Codex、人和系统消费者。
- `correlation`：task、intent、session、run、opportunity、experiment 等谱系 ID 的稳定
  `sha256:<24hex>` 不透明值；同一原始 ID 仍可跨领域关联，但不会被观察结果公开。
- `source`：只含逻辑来源名、行号和原始行 SHA-256，不输出绝对路径。
- `attributes`：只允许短标量和标量数组；自由文本、目标、命令、参数、输出和证据只能
  记录 `*_sha256`、`*_present`、长度或数量。

事件 ID 和摘要用于完整性与去重，不代表事件内容已被复制。观察结果是可重建投影，删除
后可从原领域日志再次生成。

每个 snapshot 还带三个读取切面字段：

- `stateVersion`：投影折叠语义版本；Adapter 语义变化必须递增，旧缓存整行作废而不迁移。
- `asOfSeq`：本次切面覆盖的非空来源行零基水位；无来源时为 `-1`。
- `sourceRevision`：本次实际读取的全部逻辑来源、字节长度和内容摘要形成的确定性版本，避免
  仅凭相同 `asOfSeq` 把重写后的另一份日志误当成同一切面。

## 增量尾部重放缓存

`projections/event-observer-v1.json` 是纯派生、可删除的解析检查点，不是新的事件事实源。每个
来源检查点绑定 `stateVersion`、逻辑来源身份、完整字节 offset、精确 prefix SHA-256、物理
行水位、脱敏事件和健康报告。读取时先重新取得权威文件切面：

1. 当前字节仍以缓存 prefix 开头，才复用旧折叠结果并只解析 offset 之后的 tail；
2. 来源被重写、截短、换身份、缓存 schema/版本不匹配或缓存事件未通过公共契约校验时，直接
   从来源第 0 行全量重建，缓存值没有投票权；
3. 新 tail 撕裂或违规时仍公开 contract violation，并保留上一份健康 prefix 检查点；来源
   修复后从旧水位继续，绝不截断或“修好”领域日志；
4. 缓存写采用整文件原子替换、0600 权限、64 MiB 上限和 fail-soft 语义。写失败只让下次多
   重放，不让观察失败，也不可能产生领先于来源的幻影事件；
5. 缓存路径固定在 KB `projections/` 内，任何 symlink 越界都会禁用缓存。缓存只持久化已脱敏
   公共事件，原始 prompt、目标、session、命令和证据不会被复制。

因此 `read_only=true` 表示对领域事实和控制面只读；实现可以刷新上述可删除缓存，且
`authoritative_sources_unchanged=true` 必须始终成立。CLI/MCP snapshot 暴露
`projectionCache` 命中/尾部/重建诊断；稳定状态灯只暴露 stateVersion、asOfSeq 和
sourceRevision，不把“首次重建/随后命中”这种瞬态差异当健康变化。

## 隐私模式与一次性导出

`privacy/observation-policy.json` 只控制**派生观察数据面**，不控制 Intent、Effect、Approval、
Correction、Run 等权威事实账本，也不会关闭 Guardian。缺少配置时默认 `local`，保证升级后
现有本机状态/治理消费者继续工作；显式配置损坏或使用未知 mode 时失败闭锁为 disabled，
不能把“没有读取”报告成健康的 0：

| mode | 本地 CLI/MCP 投影 | tail cache | 可携带文件 |
|---|---|---|---|
| `local` | 可用 | 可用 | 禁止 |
| `approved-export` | 可用 | 可用 | 每份都需要当前宿主一次 live UserPromptSubmit 批准 |
| `disabled` | 不发现/读取事件源 | 不读不写 | 禁止 |

通过 `set-privacy --mode disabled` 关闭时会删除可重建的观察 cache、取消尚未决定的观察导出
问题并删除本机冻结提案；不会删除权威日志、已经由人批准写到目标目录的历史导出文件或只含
摘要的导出审计。直接手改策略文件只改变后续访问，不承诺完成这次清理，因此正常操作应使用
CLI。`sulde-status` 在有效 disabled 下暴露 `event_observation_enabled=false`，事件契约健康、
计数和 violations 均为 unavailable/`null`，不会显示假绿；策略损坏另以
`event_observation_privacy_healthy=false` 告警。

`approved-export` 也不等于网络授权。导出走以下闭环：

1. 观察器使用与本地查询相同的 Adapter、过滤器、排序和 limit，先在 KB 私有目录以 0600
   冻结一份已经脱敏的精确切面；它绑定 `stateVersion/asOfSeq/sourceRevision`、目标文件、
   查询范围和返回数量，最大 64 MiB。
2. CLI 输出自然语言决策卡，披露范围、数量、目标、包含/排除项与“不会授权网络发送”；人只需
   Agent 在当前宿主展示观察导出的原生 Allow/Deny；人只作选择，不输入固定短语或复制 digest。
3. Hook 将回复与唯一开放的 `approval.asked`、provider、native session、合同 revision、回执
   和 live host observation 配对。直接调用内部决定函数或伪造 actor/receipt 不能导出。
4. 执行先消费一次性批准，再把完整 JSON 写入同目录临时文件并以不覆盖语义原子发布；失败也
   消费该批准并明确报错，不能盲重试。成功/失败/拒绝后删除冻结事件 payload，只保留摘要审计。

批准的是冻结时看到的精确切面，而不是“批准后再抓一份近似数据”。这是必须的，因为批准问题
与决定本身也会进入统一事件流；若批准后重抓，会把未经审阅的新事件静默扩入导出。生成的文件
仍只授权本地落盘；上传、邮件、GitHub 或其他外部发送必须另走 Intent Guardian 外部写入审批
与结果验证。

机器契约位于 `templates/events/sulde-observation-event-v1.schema.json`；同目录的
`positive-observation-event-v1.json` 必须通过运行时校验，`negative-observation-event-v1.json`
必须被拒绝，避免文档示例与代码边界分叉。

## 已声明来源

当前适配器覆盖：

| 领域 | 权威来源 |
|---|---|
| 宿主生命周期 | `host-capabilities.jsonl` |
| 意图 | `intent/**/*.events.jsonl`、`intent/**/*.{interventions,corrections}.jsonl`、显式 workspace 的 `.codex-agent/*.intent.{events,interventions,corrections}.jsonl`、已清理 L3 的 `interventions/archive/*/events.jsonl` |
| 审批与执行 | `intent/**/*.approvals.jsonl`、`self-repair/approvals.jsonl`、`self-repair/executed.jsonl`、显式 workspace 的 `.codex-agent/*.{intent.approvals,run}.jsonl` |
| 知识与记忆 | `recall-log.jsonl`、`mem-adoption-log.jsonl`、`mem-adoption-health.jsonl`、`feedback-log.jsonl` |
| 沉淀与评估 | `sediment-runs/decisions-*.jsonl`、`golden-review-decisions.jsonl` |
| 治理与进化 | `governance/history.jsonl`、`evolution/decisions.jsonl` |
| 通知 | `notify-log.jsonl`（只投影消息长度和摘要） |

`backups/`、`mem-sync-repo/` 和 L3 原始 provider stream 不进入观察面。前两类是副本而非新
事实，原始 provider stream 可能含完整参数，并且其可治理动作已经由 Intent audit 记录。

## CLI

```bash
# 聚合统计；不返回事件行和来源明细
python3 scripts/kb/event-observer.py summary

# 查看最近 20 条意图事件
python3 scripts/kb/event-observer.py events --domain intent --limit 20

# 加入某个显式工作区的 L3 Intent audit，并按关联 ID 过滤
python3 scripts/kb/event-observer.py events \
  --workspace /path/to/project \
  --correlate task_id=approved-task

# 验证所有已声明来源；0=通过，1=契约违规，2=调用错误，3=观察不可用
python3 scripts/kb/event-observer.py verify

# 查看/切换派生观察数据面的隐私模式
python3 scripts/kb/event-observer.py privacy
python3 scripts/kb/event-observer.py set-privacy --mode approved-export

# 冻结并显示可读导出决策卡（此时尚未创建目标文件）
python3 scripts/kb/event-observer.py prepare-export \
  --contract /path/to/workspace.active.json \
  --workspace /path/to/project \
  --output /path/to/new-observation-export.json

# Codex：Agent 用 intent-guardian native-decision-preview observation-export
# 发起当前会话 PermissionRequest；人只按 Allow/Deny。其他宿主使用可读批准/拒绝选择。
# 批准后由 Agent 消费该提案；不覆盖已有文件，也不授权上传。
python3 scripts/kb/event-observer.py export \
  --contract /path/to/workspace.active.json \
  --proposal <proposalDigest>
```

`verify` 的退出码 3 表示观察被有效关闭或策略不可用；这既不是契约通过，也不是来源违规。

`summary`、`events` 和 MCP `event_observe` 都返回同一组 `stateVersion/asOfSeq/sourceRevision`；
调用方比较切面时必须同时检查版本和 revision，不能只用事件数量或生成时间。

过滤器接受调用方已知的原始 ID，并在本地用同一规则转成不透明值；输出不会回显原始 ID。

`sulde-status.py --json` 暴露 `event_contract_*`、`event_observations_*`、`effect_*` 和
`interventions_*` 字段。周治理将 `event_contract_violations <= 0`、
`interventions_open <= 0`、`effect_blocking <= 0`、`intervention_invalid_stores <= 0`
作为确定性不变量；这些不是可调质量阈值。历史上经人选择终止或已经消费重试授权的旧
unknown 仍保留事实，但不会与当前阻断中的 effect 混成同一个计数。
L3 清理前生成的 intervention archive 带事件流摘要和原 contract identity；状态读取会重放并
校验它，观察器则用 contract identity 作为逻辑来源，因此同一行从 live worktree 移入归档
后不会生成第二个 observation event。

Claude Code/Codex 也可通过 `sulde-kb` MCP 的只读 `event_observe` 查询同一投影。该工具
默认只返回摘要；显式 `include_events=true` 才返回最多 200 条脱敏事件，并且不接受任意
文件路径，因此不能借观察接口读取未声明日志。

## 正反样本

### 正样本：跨域追踪同一任务

审批日志和执行日志都带相同 `slug`。适配后两条事件分别属于 `approval` 和 `execution`，
但共享同一个不透明 `correlation.task_id`，观察者可以还原“批准 → 执行结果”，原始 slug
不会进入投影，原文件也不发生变化。

### 正样本：保留证据而不复制内容

Intent audit 中的目标路径、沉淀候选正文和执行检查输出只形成摘要、存在标记和数量。需要
调查时，授权消费者回到 `source.name + source.line` 对应的事实源读取原文。

### 正样本：unknown 转人工后继续保持身份

EffectAttempt、Intervention、人工 decision 与后续 retry attempt 分别投影为事件；它们通过
intent/session/task 关联，attempt/intervention ID 只以摘要出现。观察者可以看出
“派发 → unknown → 人授权一次重试 → 新 attempt”，但不能从投影取得远端目标或人工证据
原文，也不能通过观察接口执行 resolve/resume。

### 正样本：纠正进入边界但语义仍未知

用户纠正只以内容摘要和 lane 摘要进入事实源。观察面可以展示
`proposed → queued → applied` 以及 PreTool/Stop/managed-run 边界，但固定输出
`semantic_acceptance=unknown`；它不能把一次 Hook 回调夸大为“Agent 已理解正确”。

### 正样本：批准问题与决定可配对但不泄露内容

`approval.asked` 与 `approval.decided` 投影到同一个不透明 intent/session lane；观察者可以证明
问题先于决定并看到 approved/rejected/cancelled/unavailable，但看不到提案、事件目标、回执或
原生 session。缺少 asked 的决定在权威账本层已被拒绝，观察面不会替它补造问题。

### 反样本：把完整 payload 放进 attributes

`prompt`、`command`、`arguments`、`message`、`reason`、`evidence`、`target` 等键会被契约
直接拒绝，不能为了“调试方便”绕过脱敏边界。

### 反样本：自动兼容未知 schema

未知行不会猜测类型或静默升级。它被计为 `unsupported_rows`，令验证退出 1，并在状态和
治理中形成契约违规。新增格式必须先增加适配器及正反样本。

### 反样本：观察者修复或搬迁事实源

观察者不得截断尾行、重写历史、跟随日志 symlink、补写公共信封或把多个日志合并落盘。
修复属于原生产者，观察面只报告可验证事实。

## 能力边界

该投影可以回放 Sulde **观察到的治理事实**，不能重放 Claude Code/Codex 的隐藏推理、
完整上下文或模型内部状态。没有完成回调的动作仍应保持 `unknown/inconclusive`，不能从
后续文件变化倒推成成功。观察器也不是命令总线：人工裁决只能写回原 Intervention 事实源。
