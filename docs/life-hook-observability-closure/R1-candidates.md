# R1 沉淀候选（待单写者判重）

按 `templates/knowledge/problem-card.md` 保存必要事实；不写事实知识库。以下 verified 仅限所列隔离证据，不含历史业务故障归因或 Desktop 验收。

## 候选 1：宿主结果入口与自动送达

### 任务与意图

- 问题类型：host-inconsistency / bug-fix。
- 任务目标：工具成功后 Hook 失败应被独立采集、聚合和回读。
- 用户真实预期：真实 PostToolUse 自动链，不能用 SessionStart 或人工搬运代替。
- 触发场景：CLI 和 Desktop 共存或能力不同，插件、项目 Hook 同时运行。

### 观测与证据

- 可观察症状：真实 CLI 工具 exit 0，但其 JSON/transcript 没有 Hook 完成结果。
- 期望与实际差异：工具成功流不能直接提供完整 Hook 审计。
- 已确认根因：当前被测 CLI 的输出接口缺少该事件；app-server 通知只属于连接的进程。Desktop 实际入口仍 inconclusive。
- 已排除假设：CLI 没有 Hook 结果不等于 Hook 未运行；隔离 app-server 不能证明正在运行的 Desktop 已接入。
- 证据状态：verified（CLI 自动链）；inconclusive（Desktop 和历史事故）。
- 一手证据：`tests/test_native_posttool_delivery.py`、`R1-native-posttool.json`、`R1-tests.json`；原生 4 次工具、12 条失败事实，0 次 ingest。
- 正确做法及验证：在支持的自有 Hook 命令中记录，原生 Stop 自动聚合，独立进程回读；工具、Hook、审计各自结算，业务效果仍 unverified。

### 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | CLI 动作成功却出现 Hook 非零，需要核验结果入口 | apply | 同时涉及工具与 Hook 两种结果 | observed |
| 路由反例 | 只有普通工具命令自身返回 1，已确认没有 Hook | skip | 不存在宿主 Hook 送达问题 | constructed |
| 执行合格例 | 真实 PostToolUse 写入、Stop 聚合、独立回读，动作计数不增加 | pass | 自动链和无重放均有证据 | observed |
| 执行失败例 | 把另一 app-server 的 SessionStart 通知手工转存，宣称 Desktop PostToolUse 已覆盖 | fail | 宿主、事件和自动送达均不相符 | constructed |

### 上浮边界

- 必须删除或泛化：项目名、机器路径、会话 ID、业务工具输入、提交及临时目录。
- 可跨项目复用的内核：先验证宿主可提供的结果接口，再结算自动观测范围，盲区保持 open。
- 建议容器：platform-kb；候选消费者：Hook 适配器、诊断 Skill、发布 review。

## 候选 2：观测成功路径的进程与导入成本

### 任务与意图

- 问题类型：performance。
- 任务目标：保留失败证据，减少每次成功调用的同步观测开销。
- 用户真实预期：测量前定预算；同机同解释器给样本数、中位数、p95；不能把新增约 50 ms 称为提升。
- 触发场景：短命 Python Hook 被额外 Python 包装器包裹。

### 观测与证据

- 可观察症状：旧包装器明显增加普通调用延迟，多轮优化仍一度超出预算。
- 期望与实际差异：业务脚本很短，但解释器、导入和等待时间占主要成本。
- 已确认根因：旧观测器额外进程、急切导入、带 timeout 的轮询等待；数据库写入占剖析总时间约 1.7%。
- 已排除假设：不是数据库写入或重复 record 主导；剖析每调用 1 次 record。等待包含子进程有效执行，不能全算浪费。
- 证据状态：verified（被测包装器范围）。
- 一手证据：`R1-latency-py310.json`、`R1-latency-py314.json`、`R1-cost-breakdown.json`、`R1-performance-history.json`。
- 正确做法及验证：稳定桥接复用进程，推迟可选导入，失败后有界采集；3.10 普通包装器新增中位数 14.147 ms/p95 17.094 ms，保留所有未达标记录。

### 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 短命 Hook 加观测后每次增加几十毫秒 | apply | 启动/导入成本可能超过有效执行 | observed |
| 路由反例 | 单一长驻进程发生数据库锁竞争，已无重复解释器启动 | skip | 已知瓶颈及进程模型不同 | constructed |
| 执行合格例 | 固定预算、保留失败轮次、同环境测量并减少额外进程 | pass | 改进与预算通过有可复核样本 | observed |
| 执行失败例 | 增量 17.8 ms 超过 15 ms 后改预算为 20 ms | fail | 事后改变完成标准 | constructed |

### 上浮边界

- 必须删除或泛化：机器及项目身份、绝对路径；保留解释器版本和统计口径。
- 可跨项目复用的内核：先计量进程和导入，再优化同步路径；独立控制与嵌套计时不可伪装成可相加的因果占比。
- 建议容器：case-studies；候选消费者：性能诊断 Skill、Hook review。

## 候选 3：候选验证必须绑定实际 Python 环境

### 任务与意图

- 问题类型：regression / workflow。
- 任务目标：prepare、verify、install 使用同一经过验证的解释器和依赖。
- 用户真实预期：默认缺依赖时尽早明确失败，不试找其他 Python、不静默全局安装。
- 触发场景：多个 Python/venv 共存，解释器二进制相同但依赖及目标数据根不同。

### 观测与证据

- 可观察症状：默认解释器无 PyYAML；旧安装流程直到 MCP 阶段才发现目标 venv 缺失并回滚。
- 期望与实际差异：候选验证过的解释器不等于目标 MCP 已有可用运行时。
- 已确认根因：此前只有解释器二进制身份/晚期 launcher 检查，没有在生产切换之前要求目标运行时和依赖一致。
- 已排除假设：二进制哈希一致不能证明 venv 依赖相同；无关日志并非环境漂移。
- 证据状态：verified（隔离环境和安装）。
- 一手证据：`tests/test_python_environment_preflight.py`、`R1-release-history.json`、`R1-release.json`、`R1-tests.json`。
- 正确做法及验证：确定一个解释器，内容预检并沿流程复核；目标缺 venv 在锁/注册表之前拒绝；仅给明确的隔离环境修复路径。

### 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 候选验证通过，目标安装运行时却找不到 yaml/venv | apply | 验证环境与执行环境没有完整绑定 | observed |
| 路由反例 | 无 Python 依赖的静态资源部署失败于权限不足 | skip | 不涉及解释器或依赖内容 | constructed |
| 执行合格例 | 缺依赖先拒绝，显式准备隔离 venv 后 3 次安装验证通过，依赖漂移使回执失效 | pass | 同一环境和切换前门禁均被验证 | observed |
| 执行失败例 | 缺 yaml 后遍历其他 Python 或全局 pip install，继续使用旧回执 | fail | 改变环境且复用了失效证据 | constructed |

### 上浮边界

- 必须删除或泛化：个人 Python 路径、机器及候选目录、真实环境全量清单。
- 可跨项目复用的内核：明确环境选择，绑定依赖内容，切换前预检，环境漂移后重新验证。
- 建议容器：anti-patterns；候选消费者：安装器、发布 verifier、review checklist。
