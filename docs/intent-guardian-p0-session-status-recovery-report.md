# Intent Guardian P0：会话状态与可恢复性修复报告

## 结论

本批次修复了新会话状态路径同步重放全局历史、状态观察器自锁、sealed runtime 被
Python 字节码污染后无法恢复，以及多会话并发时隔离门禁把外部生产写入误判为测试越界
四条相互放大的故障链。受影响范围官方隔离门禁 149/149 通过（3 项平台跳过）。

本报告不是生产安装或 R97 program accepted 的权威事件。源码尚未安装到生产 Sulde，
仓库完整套件仍有已在未修改 `main` 上复现的基线红项，必须在后续独立任务中关闭。

## 范围与非目标

- 修复 Codex SessionStart 状态展示、稳定 launcher、Codex adapter、状态观察器与测试隔离门禁。
- 提供只针对 generation-sealed Codex runtime 的派生字节码恢复入口。
- 不重建意图守卫任务图，不安装生产插件，不切 scheduler，不修改 `main`，不处理历史审批语义。

## 已确认根因与处置

1. SessionStart 直接运行完整 `sulde-status.py --statusline`，生产样本耗时 4.19 秒；profile
   显示约 9834 万次调用，事件投影重放约 3.1 万条事件，占 8.816 秒 profile 时间。
   现改为读取最大 16 KiB、0600、三小时有效的状态快照；缺失、过期或不安全时在一秒内
   返回黄色降级，不扫描事件、干预或记忆历史。
2. `status-notify` 发现告警后返回非零，scheduler 下一轮又把观察器自身的历史退出码视为
   scheduler 故障，形成反馈自锁。现将“成功观测到告警”和“观察器执行失败”分开：notify
   成功完成恒为零，其他真实 scheduler 失败仍进入红灯。
3. Python import 在 sealed runtime 中生成 `__pycache__/*.pyc`，导致完整树 digest 变化，
   launcher fail-closed；重复测试夹具又会把未跟踪缓存复制进制品，产生 generation 缺失级联。
   所有 staging、install、bootstrap、adapter 和生成 launcher 路径现禁写字节码；封存后再次
   复核 digest；测试制品明确排除缓存。
4. 新增 `repair-bytecode` 只在“排除字节码后的树仍精确等于 sealed generation”时删除
   `.pyc/__pycache__`。源码漂移、软链接、未知缓存内容或无 generation 的 runtime 一律拒绝；
   Claude/源码路径不会收到不可执行的修复建议。
5. 官方隔离门禁原先把其他活跃 workspace 对同一生产 KB 的合法并发写入当成测试越界。
   现先用 `python -S` 在 OS 沙箱内主动证明生产写入被拒绝，再保留 Python audit hook 判红；
   两层成立后，其他会话的生产变化单独报告为外部并发告警，不再覆盖测试退出码。

## 安全与边界

- 快照读取有固定字节上限，拒绝最终文件或 `projections` 目录软链接、非普通文件、权限过宽、
  非当前 owner、控制字符、未知 ANSI、超长内容和远未来时间戳。
- 快照写入使用同目录 0600 临时文件、`fsync` 和原子替换；发布失败进入 notify 告警，
  不再通过非零退出反向污染 scheduler。
- 隔离门禁未关闭生产写防线；原生 write-denial proof 失败或 Python 子进程有写尝试仍返回 3。
- 历史审计债务不再把当前运行灯染黄，但仍保留在 JSON/通知/治理报告，未被删除或视为解决。

## 验证证据

- 聚焦回归：97 tests PASS，2 platform skips（stage/install/bootstrap/statusline/launcher）。
- 边界补强回归：60 tests PASS；发布授权与门禁回归 48 tests PASS，1 platform skip。
- 最终官方隔离门禁：149 tests PASS，3 platform skips，生产写拒绝 proof 通过；另一活跃
  workspace 的 contract/approval/event 写入被报告为外部并发告警。
- 完整官方套件：1310 tests，10 failures、16 errors、6 skips。失败分类：
  - linked worktree 不满足 native broker/full-clone 测试的真实 `.git` 目录前置条件；
  - 系统 Python 缺少 `numpy`，`test_rerank` 无法导入；
  - 审批、事件投影、guardian recovery 与 subprocess 编码守卫存在未修基线红项；其中
    7 个审批/投影/恢复代表用例及编码守卫已在未修改 `main` 上同样复现；
  - 本批次引入的 release authorization inventory 遗漏已修复并独立通过。
- `git diff --check` 通过；回归后源码树没有 `__pycache__`。

## 后续严重问题

1. P0：为正式全套验收建立真正 full clone 的可重复 runner，并固定包含 `numpy`、PyYAML 的
   解释器/依赖 generation；linked worktree 不得冒充 full-clone 生产边界。
2. P0：修复未修改 `main` 已存在的 approval pair、event observer、guardian recovery 基线红项；
   当前测试与更严格的资源身份、card digest、历史 replay authority、pathname alias 语义不一致。
3. P1：修复 `intent_critic.py` 一处、`intervention.py` 两处 text subprocess 未固定
   `encoding="utf-8", errors="replace"` 的仓库守卫违规。
4. P1（证据不足）：确认活跃 workspace `a092…` 的持续生产写入是仍在使用的另一终端，还是
   陈旧跨 workspace/session 绑定；在确认前不得删除其 contract 或审计链。
5. 发布门：本批次进入 `dev` 后仍需 stage、安装事务预检、生产安装授权和新会话 canary；
   当前源码通过不代表已安装 Sulde 已修复。

## 沉淀候选

### 候选一：sealed Python runtime 被派生字节码污染

#### 任务与意图

- **问题类型**：host-inconsistency / regression
- **任务目标**：让 digest-bound 插件在重复启动和验证后仍可启动，并能安全恢复纯派生污染。
- **用户真实预期**：测试通过后的制品在真实宿主中也必须可重复运行，不能因自身 import 失效。
- **触发场景**：Python 源码树整体封存，launcher 对完整树做 digest 校验，宿主随后 import runtime。

#### 观测与证据

- **可观察症状**：`runtime digest changed` 反复阻断 Hook；测试后下一轮 staging 大量级联失败。
- **期望与实际差异**：期望验证只读；实际 import 生成 `.pyc`，验证动作改变了被验证对象。
- **已确认根因**：入口未统一禁写 bytecode；测试夹具又把未跟踪 cache 当发布输入复制。
- **已排除假设**：不是源码内容漂移；排除 bytecode 后的树与 sealed generation 精确一致。
- **证据状态**：verified
- **一手证据**：隔离测试的 `__pycache__` tree-digest 失败；修复后 149 项官方门禁通过且无 cache。
- **正确做法及验证**：入口与子进程禁写；封存后复核；恢复前先证明 normalized digest 完全一致。

#### 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | sealed Python 插件首次能跑，第二次报 digest changed，树中只有 `.pyc` 新增 | apply | 同时具备完整树封存与派生缓存污染 | observed |
| 路由反例 | 普通开发源码改动后单测失败 | skip | 没有 sealed generation，也不是派生污染 | constructed |
| 执行合格例 | 删除前 normalized digest 精确命中封印，删除后 strict digest 恢复 | pass | 不会掩盖源码或未知文件漂移 | observed |
| 执行失败例 | 看到 `__pycache__` 就递归删除并重签 generation | fail | 扩大删除且可把真实漂移重新授权 | constructed |

#### 上浮边界

- **必须删除或泛化**：本机路径、插件名、版本、generation 值。
- **可跨项目复用的内核**：验证不可改变 digest-bound 对象；派生恢复必须先匹配规范化封印。
- **建议容器**：anti-patterns
- **候选消费者**：发布脚本、插件安装器、artifact integrity checklist

### 候选二：共享生产状态使隔离测试产生并发假失败

#### 任务与意图

- **问题类型**：workflow / host-inconsistency
- **任务目标**：证明测试不能写生产状态，同时允许同机其他真实会话继续工作。
- **用户真实预期**：并行提高效率时，其他会话活动不能让代码全绿的门禁随机失败。
- **触发场景**：测试子进程已隔离，但门禁用生产目录 before/after 全量相等作为测试纯度判据。

#### 观测与证据

- **可观察症状**：141 项断言全绿，最终仍因另一个 workspace 的 contract/events 变化返回失败。
- **期望与实际差异**：期望检测测试写入；实际检测到的是所有进程的生产写入且无法归属。
- **已确认根因**：全局状态相等判据混淆 child causality 与 external concurrency。
- **已排除假设**：Python audit 无测试写尝试；OS 沙箱 write-denial 主动 proof 通过。
- **证据状态**：verified
- **一手证据**：两轮 141 项全绿后仅生产 metadata 判红；最终 149 项以外部并发告警完成。
- **正确做法及验证**：先证明原生只读边界，再把 child audit 与外部状态变化分域报告。

#### 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 测试全绿但共享生产目录因另一会话 append 而门禁失败 | apply | 失败来自无法区分写入主体 | observed |
| 路由反例 | 两个测试任务共写同一临时输出目录 | skip | 是测试间共享 fixture，不是生产外部并发 | constructed |
| 执行合格例 | 原生拒写 proof + child audit，无 child 写则外部变化告警但保留测试码 | pass | 既证明隔离又不要求全机静止 | observed |
| 执行失败例 | 发现并发后关闭生产 snapshot 比对和所有写审计 | fail | 失去测试越界检测能力 | constructed |

#### 上浮边界

- **必须删除或泛化**：workspace hash、用户目录、具体会话 ID。
- **可跨项目复用的内核**：共享状态变化不等于被测子进程写入；纯度判据必须包含因果边界。
- **建议容器**：anti-patterns / work-model
- **候选消费者**：CI runner、并行测试编排、Hook/MCP 状态测试

### 候选三：交互状态热路径同步重放历史并形成观察器自锁

#### 任务与意图

- **问题类型**：performance / workflow
- **任务目标**：新会话立即展示有界状态，后台告警不反向制造新的 scheduler 故障。
- **用户真实预期**：状态展示不能挂起宿主，也不能因历史债务让当前控制面永久红灯。
- **触发场景**：SessionStart 同步调用全局 collector；同一观察 job 的告警退出码又是 collector 输入。

#### 观测与证据

- **可观察症状**：SessionStart “状态脚本无输出”或超时；status job 非零后 scheduler 持续降级。
- **期望与实际差异**：期望状态是有界只读投影；实际同时执行全历史审计并观察自己的失败。
- **已确认根因**：交互热路径与后台 collector 未分层，观察成功与系统健康使用同一退出码。
- **已排除假设**：不是单纯提高 timeout 可解决；生产 profile 的耗时随事件历史线性增长。
- **证据状态**：verified
- **一手证据**：生产 4.19 秒/约 9834 万 calls；10 万历史行 SessionStart 回归小于 1 秒。
- **正确做法及验证**：后台发布小快照，前台有界读取；notify 成功与 payload 健康正交。

#### 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 启动 Hook 随历史日志增长变慢，观察 job 上次非零又使自己继续非零 | apply | 同时命中热路径放大与自反馈 | observed |
| 路由反例 | 单次后台治理报告本来就需要全量扫描 | skip | 不在交互延迟预算内且无自反馈 | constructed |
| 执行合格例 | 后台快照原子发布，前台固定上限读取，缺失时快速黄色降级 | pass | 延迟与历史规模解耦且 fail-soft | observed |
| 执行失败例 | 仅把 SessionStart timeout 从 3 秒提高到 30 秒 | fail | 延迟仍随历史增长并继续占用宿主 | constructed |

#### 上浮边界

- **必须删除或泛化**：具体事件数量、机器 profile 路径、scheduler label。
- **可跨项目复用的内核**：交互状态消费预计算投影；观察器执行成功与被观察健康必须分离。
- **建议容器**：anti-patterns / work-model
- **候选消费者**：SessionStart Hook、statusline、scheduler health、性能验收清单

