---
doc_id: work-model/schema-fixture-migration-and-real-execution
container: work-model
platform: cross
summary: 协议或 schema 收紧后必须全仓迁移 fixture，并证明关键测试既进入语法/编译阶段也在生产路径实际执行，不能靠测试名和 test-mode 旁路冒充覆盖。
related: [ap-0199, ap-0200, ap-0201, work-model/evidence-gate-contract]
sedimentation_schema: 2
problem_type: regression
evidence_status: verified
---

# Schema 收紧后的 fixture 迁移与真实执行覆盖

## 问题原型

生产协议新增必填字段或独立校验表后，旧测试 fixture 缺 provenance、回执或身份字段。为恢复绿测，
实现者放松校验器或让 test mode 绕过生产解析；预检脚本只检查测试名出现，却没有把它加入实际执行
阶段。混合 shell/Python 文件还可能被错误解析器验证，制造与项目无关的假失败。

## 根因与证据

根因是把 fixture 当作可以落后于生产不变量的样例，并把“名字存在/能编译”当成“生产链已覆盖”。
已验证修复需要全仓找到 fixture 构造点统一迁移，从真实输入贯穿 parser、broker、receipt、managed
process 和下游 verifier；约束同时核对 syntax/compile 与 execute 清单。按文件类型运行 `bash -n`
和 Python compile 后，验证命令自身的错误不再污染产品结论。已排除“保留旧 fixture 兼容字段可选”——
这会让生产不变量重新变成可绕过。

## 适用边界

- 适用于 schema、协议、回执、任务权威和受管进程不变量升级。
- 纯展示性测试数据新增非安全字段时可提供显式版本迁移，但不能无版本静默兼容。
- 编译成功只证明语法/类型；需要运行时或外部行为的断言必须实际执行。
- setup/宿主权限失败与业务断言失败分开，不把未进入测试体写成 PASS 或代码 FAIL。

## 判定样本

### 路由正例

- **输入**：新增必填 provenance 后旧测试失败，提议把字段改回可选；或测试名在脚本中但从未执行。
- **预期**：apply
- **原因**：生产不变量与 fixture/执行覆盖发生漂移。
- **来源**：observed

### 路由反例

- **输入**：版本化 API 明确支持 v1/v2，两套 fixture 均经过各自完整生产 parser。
- **预期**：skip
- **原因**：这是显式兼容协议，不是 test-mode 绕过。
- **来源**：constructed

### 执行合格例

- **做法或输出**：全仓枚举 fixture 构造点并迁移；产物全部写临时目录；同一真实输入通过生产 parser、
  broker 和 verifier；预检约束证明关键测试同时处于语法/编译与实际执行集合；shell/Python 分别验证；
  受支持宿主完整运行通过。
- **预期**：pass
- **原因**：生产和测试共享不变量，且覆盖由运行证据证明。
- **来源**：observed

### 执行失败例

- **做法或输出**：`if TEST_MODE: return valid`，或测试名写进数组但 runner 不消费；失败测试还向生产
  默认路径写 artifact。
- **预期**：fail
- **原因**：绿测来自旁路、虚假覆盖或环境污染。
- **来源**：observed

## 正确做法

1. 先冻结新 schema/协议不变量和版本边界，再全仓检索 fixture 生成、复制和快照点。
2. 批量迁移 fixture，补真实 provenance/身份/receipt；禁止填无意义占位值。
3. 测试输出、失败诊断和 latest 指针全部注入临时根，任何默认生产路径写入都判失败。
4. 真实输入贯穿生产 parser、适配器、broker、进程和独立 verifier，test mode 只能选择 fixture，不能跳过协议。
5. 约束脚本分别核对发现、语法/编译和执行列表；任一关键测试缺执行即失败。
6. 按文件类型选择验证器；先证明验证命令本身成立，再解释项目结果。

## 执行流程

`freeze schema → inventory fixtures → migrate → isolate outputs → syntax/compile → execute production chain →
verify coverage lists → clean-room rerun`。

## 验收与失败处理

旧 fixture、缺字段、额外字段、test-mode bypass、未执行测试、生产路径写入和错误解析器均有负例。
外层环境无法运行时结论为 `environment_blocked`，不得覆盖已完成的语法证据或宣称 runtime PASS。

## 消费与防复发

schema review、fixture builder、test runner、preflight、生产协议和报告器共同消费。CI 固定“测试名同时
出现于发现/编译/执行集合”以及“临时根外零写入”两条机械门禁。
