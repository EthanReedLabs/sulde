---
doc_id: "work-model/evidence-gate-contract"
container: work-model
platform: none
summary: "证据门禁绑定目标、运行和发布范围；复用测试必须证明输入等价，安装退出成功不能替代本次授权消费、独立效果验证或真实宿主证据。"
related: [ap-0210, ap-0231, ap-0252, work-model/governance-observation-contract, work-model/canonical-byte-authority-self-hosted-verification, work-model/content-addressed-device-fixture-lifecycle, work-model/final-backup-before-migration-cutover, work-model/machine-readable-stage-control-plane, work-model/schema-fixture-migration-and-real-execution, work-model/ownership-aware-receipt-locks]
sedimented_by: auto
sedimentation_schema: 2
problem_type: workflow
evidence_status: verified
---

# 证据门禁的来源、格式与时序契约

## 问题原型

多阶段任务把 `PASS/READY`、文件存在或某一子阶段成功当成总体完成，却没有把阈值、参数、
run identity、构建/设备范围和终态证据沿整条调用链传播。结果是局部绿灯覆盖总体短缺，或旧 run、
另一设备和文档示例被误收为当前验收证据。

## 根因与证据

根因是控制状态与事实证据分离后，只传播了布尔 verdict，未传播生成 verdict 所需的完整身份、
阈值和来源。已观察到的修复模式是：顶层门禁重算全部分区与总体阈值，终态链引用不可变 evidence
ID，所有子命令显式接收同一参数集，且后来的同 scope 正样本才可关闭旧失败。缺任一绑定时，
fixture 能构造“状态 PASS、证据为空/过期/属于另一 run”的假通过。

已验证的发布变体还区分三种身份：被测试输入、当前发布件和本次执行授权。
纯版本/记录差异在精确证明被测输入未变时可复用源码测试，新的 artifact 仍须独立验证；
旧 helper 的成功响应不能充当新维护动作的 grant 消费或效果结算证据。
一次最终成功也不能反推出旧失败的具体分类根因已经确认。

## 适用边界

- 适用于构建、设备采集、迁移、发布、模型评测和多 Agent 总纲等分阶段验收。
- 单个纯函数断言若终态与证据边界完全一致，可不引入跨阶段 evidence ledger。
- 人工判断可以成为一个有身份和时效的证据项，但不能替代机器可观测的构建、设备或外部事实。
- 总体阈值、分区阈值和命令参数都必须显式；缺失时判 `INSUFFICIENT`，不得猜默认值。

## 路由正例

- **输入**：子阶段都写 PASS，但总体阈值和 run identity 没有向下传播，顶层也未重算总数量；
  部分证据还来自旧 run 和另一设备。
- **预期**：apply
- **原因**：状态、总体阈值、run identity 与设备 scope 没有形成同一证据合同。
- **来源**：observed

补充样本：

- **输入**：已验收源码只追加版本与发布记录，却要求无条件重跑全量；或者安装器 exit 0 后缺少本次 grant 消费和独立结算仍宣称完成。
- **预期**：apply
- **原因**：测试覆盖范围、发布件身份和执行权证据混成单一状态。
- **来源**：observed

## 路由反例

- **输入**：纯函数测试在同一进程内断言输入输出，不读取历史产物也不产生外部状态。
- **预期**：skip
- **原因**：终态证据与函数断言同边界，不存在跨阶段传播或旧证据替换问题。
- **来源**：constructed

## 执行合格例

- **做法或输出**：顶层入口冻结 run/config/threshold，子阶段回传不可变 evidence ID，最终按同 scope 重算并输出缺口。
- **预期**：pass
- **原因**：局部状态不能越过总体门禁，证据来源、参数、时序和终态均可独立回读。
- **来源**：observed

补充样本：

- **做法或输出**：回读原测试的命令、环境、源码和日志摘要，证明后续差异不改变被测输入；单独验证新发布件及本次唯一授权消费，再由独立 verifier 结算。
- **预期**：pass
- **原因**：旧测试只覆盖等价输入，新发布身份与物质效果有自己的新证据。
- **来源**：observed

## 执行失败例

- **做法或输出**：聚合器只检查每个 JSON 都有 `status=PASS`，不验证 run、阈值、证据引用和时间线。
- **预期**：fail
- **原因**：任意旧产物或手写状态都能伪造总体完成，门禁没有验证真实世界。
- **来源**：observed

补充样本：

- **做法或输出**：运行时或依赖改变后仍使用旧测试，或仅凭旧 helper exit 0/no-current-debt 宣称本次授权已消费；把失败全量加定向复验改写成最终全量全绿。
- **预期**：fail
- **原因**：遗漏新输入、当次权力使用或原始失败事实，组合结论不能重写历史运行。
- **来源**：constructed

## 真实探针而不是“字符串出现过”

门禁只读取白名单 evidence artifact，并结构化解析真实 probe 行/JSON。若只能匹配文本，
必须整行锚定并要求关键字段齐全，例如 `runId`、`scope`、`latencyMs`、`capturedAt` 和状态；
禁止递归扫描源码、README、任务书或验收说明。否则文档里的“期望输出示例”会被当成实测。

每条证据还要校验：artifact 来源、当前 build/commit、设备/配置 scope、时间窗口和 schema
版本。格式像真的但属于旧 run 或另一配置，仍是无关证据。

## 状态字段不是发布事实

`ready`、`approved`、`compliant`、`PASS` 或 `SHIPPED` 等状态字段只能保存判定结果，不能独立证明发布条件已经成立。发布门禁必须从状态追溯到对应的真实设备运行和合规证据，并重新校验这些证据与本轮发布范围一致。

设备证据至少应说明：

- 实际设备或获准等价的设备画像；
- 被验证的构建、版本与配置；
- 真实运行产生的探针指标和结果；
- 采集时间、证据标识及可追溯来源。

合规证据至少应说明：

- 当前发布范围适用的政策、声明或审查项；
- 证据对应的版本、地区、数据路径或权限范围；
- 必要的审核、批准或人工确认及其有效时间；
- 尚未完成、已过期或无法验证的阻断项。

若只有状态字段而缺少其引用的证据，或证据无法证明当前设备、构建与合规范围，判定必须是 `INSUFFICIENT`，不得默认发布。状态与证据矛盾时，以重新解析的事实证据为准，并记录矛盾供审计。

## 正向证据优先，但必须同 scope 且更新

门禁按同一 subject/scope 建立时间线：

1. 存在当前配置、通过 schema/阈值、且晚于相关失败的正样本 → PASS；历史失败保留审计，
   不再永久阻断。
2. 没有有效正样本，且存在未被后续证据关闭的相关失败 → BLOCKED。
3. 正负样本都没有，或 scope/时序不可比 → INSUFFICIENT，不得默认 PASS。

“正向优先”不是任意一条 PASS 覆盖所有失败；只有同一目标、同一配置或获批等价范围、
更晚且完整的正样本才能关闭旧失败。失败关闭关系应显式记录 `supersedes evidence_id`。

## 回归 fixture

- 文档含完整示例行、evidence artifact 为空：必须 INSUFFICIENT。
- probe 缺 `latencyMs` 或 `capturedAt`：必须拒绝解析。
- 同 scope 先 FAIL 后 PASS：最终 PASS，旧失败仍可追溯。
- 不同设备/配置的 PASS 晚于 FAIL：不得互相覆盖。
- 只有历史 FAIL：BLOCKED；清理根因但尚未重跑：仍 BLOCKED，而不是自动复活。
- 发布状态为 PASS，但没有真实设备证据：必须为 INSUFFICIENT。
- 发布状态为 approved，但合规证据已过期或不适用于当前范围：必须为 BLOCKED 或 INSUFFICIENT，不得发布。
- 状态字段与结构化证据结论冲突：必须按证据重新判定并产生审计记录。

## 判定线

门禁若不能回答“哪一个真实运行、哪个设备与合规范围、何时、用什么 schema 证明了什么”，它验证
的只是声明的状态，不是可发布的系统事实。

## 测试证据复用不是授权复用

复用前记录原运行的源码/测试选择/依赖/解释器/配置身份、日志摘要、退出码以及
源输入前后差异。只有证明差异不影响对应验收项，才保留该项结论；文档扩展名或
manifest 只改一个字段都不是自动豁免，因为这些文件也可能参与打包、规则或测试输入。
无法证明时按受影响范围补测；大范围重构或范围无法界定时运行全量。

新的发布件仍要校验构成及真实宿主必要链路；新的物质维护动作需要本次匹配的
授权消费与独立 verifier。不能复用旧 grant，也不能凭当前债务为空证明曾经执行。
若采用“原全量结果＋失败项修复复验＋未受影响范围证明”，必须逐项记录覆盖及关闭
关系，原失败运行保持失败；这不等于最终 HEAD 已重新运行全量。

测试准备、命令执行、安装、验证、人工等待与模型耗时分开报告。子阶段秒数或
分类器微秒差异不能外推成整项任务加速比例。未确认成本根因留作诊断，不写成事实。

## ✅ 正确

1. 顶层入口固定 `runId`、目标 commit/build、设备/配置 scope、总体与分区阈值、schema 版本；所有
   子命令接收并回显这些字段，禁止在中层重新采用隐式默认值。
2. 每个阶段只发布不可变 evidence artifact 和其摘要，状态由聚合器从证据重算；聚合刷新时原子
   重建 status、blocker、next-action 和 handoff，不能只改其中一个派生文件。
3. 终态链必须区分单元/fixture、隔离集成、真实宿主或设备、发布门禁；下层通过不能合成上层
   `live_verified`，缺少当前层真实证据时保持 `INSUFFICIENT`。
4. 同 scope 的新正样本可显式 supersede 旧失败；不同设备、配置、provider、session 或 run 的
   PASS 不得互相覆盖。失败与其关闭关系都保留审计。
5. 总体门禁同时验证分区完整性、总数量、唯一 identity、失败命令和证据摘要；任一失败或缺失均
   返回非零，并生成机器可读 blocker 清单。

## 消费与防复发

- 任务运行器、证据采集器、聚合器、总纲验收和 handoff 生成器共同消费同一 schema。
- 回归 fixture 至少覆盖旧 run 注入、不同 scope 的晚 PASS、参数中途丢失、分区各自达标但总量
  不足、状态文件单独更新和证据摘要漂移。
- 审查时从最终 verdict 反向追到每个 evidence ID，并复算一次；无法复算的 PASS 不得发布。
