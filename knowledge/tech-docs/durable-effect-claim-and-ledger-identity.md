---
doc_id: tech-docs/durable-effect-claim-and-ledger-identity
container: tech-docs
platform: none
summary: 一次性副作用的 claim、公开读回与安全账本必须分离执行权和观察权，并绑定稳定父目录与叶节点身份。
related: [ap-0242, ap-0247]
sedimentation_schema: 2
problem_type: design-decision
evidence_status: verified
---

# Durable claim、执行权与账本身份必须分层

## 问题原型

副作用执行器用 durable claim 保证“只执行一次”，并把请求、claim、结果和恢复状态写入本地账本。
若重放读回仍暴露 `execution_authorized`，两个消费者可能都执行；若创建账本时只检查叶文件，攻击者
又能通过父目录替换、符号链接或锁文件别名改变写入目标。

## 原则与机制

系统必须分开三类能力：首次赢家持有的一次执行权、所有调用方可见的非执行状态、以及只允许在
稳定资源身份下追加的持久化权。`already_claimed`、查询和恢复扫描都是观察，不得携带执行能力。
账本先绑定已存在 canonical 父目录的设备/inode 身份，再以 no-follow 创建 ledger 与 lock 叶节点，
每次写入前后都验证身份稳定。

## 根因与证据

根因是把“读到了成功 claim”误写成“拥有 claim 所代表的权限”，并把安全文件创建缩减成叶节点
不存在检查。并发与崩溃注入已证明：只有 CAS 首次提交者能获得执行权；公开投影移除权限字段后，
重放只读；父目录、ledger 或 lock 任一替换都会在写入前失败闭锁。已排除“用进程内锁解决”——
它不覆盖进程崩溃、PID 复用和跨进程消费者。

## 适用边界

- 适用于提交、外部写入、设备操作等需要 exactly-once 或 at-most-once 的效果。
- 纯读取不需要执行 claim，但其审计文件仍应遵守身份和 no-follow 边界。
- 幂等适配器可以安全重探测结果，但不能据此重新授予原副作用执行权。
- 父目录身份无法证明或存储只读时保持失败，不降级到临时目录冒充生产权威。

## 判定样本

### 路由正例

- **输入**：第二个消费者读到 `already_claimed` 后仍看到 execution_authorized，或账本路径父目录可被替换。
- **预期**：apply
- **原因**：执行权重放或持久化资源身份不完整。
- **来源**：observed

### 路由反例

- **输入**：无副作用的纯内存计算使用普通 memoization 并允许多个读取者。
- **预期**：skip
- **原因**：没有一次性外部效果或持久化权威账本。
- **来源**：constructed

### 执行合格例

- **做法或输出**：并发 claim 只有一名赢家获得密封执行票；其余只读状态不含权限；替换父目录、
  ledger 或 lock 的故障注入均在执行前拒绝，崩溃恢复保持同一赢家。
- **预期**：pass
- **原因**：观察、执行与持久化三种权限边界独立且可重放验证。
- **来源**：observed

### 执行失败例

- **做法或输出**：所有读回都复制首次 claim JSON，或只用 `O_EXCL` 创建叶文件而不绑定父目录。
- **预期**：fail
- **原因**：权限会被复制，或路径替换能重定向权威写入。
- **来源**：constructed

## 正确做法

1. claim 记录保存事实，执行票另行密封且只返回首次 CAS 赢家。
2. 公开/恢复投影显式固定 `execution_authorized=false`，未知字段拒绝解析。
3. 绑定 canonical 父目录身份；对 ledger、lock、receipt 使用 no-follow、普通文件和稳定 inode 校验。
4. durable append 在替换前后 fsync，崩溃边界通过前缀重放恢复。
5. adapter 完成后以独立 verifier 结算，不把 adapter 自报成功当终态。

## 取舍

额外的身份检查和 fsync 增加少量延迟，但只位于控制面写边界；它换来跨进程唯一执行和可验证恢复。
对高频纯读取不应复用该重型路径。

## 消费与防复发

GrantBroker、恢复监督器、ledger writer 和资源适配器共同消费。测试必须覆盖双消费者、崩溃前后、
父目录/叶节点/锁替换、只读存储、重复回调和公开投影字段检查。
