---
doc_id: ap-0247
container: anti-patterns
platform: none
summary: 人已经在原生界面明确 Allow，执行层却没有消费对应强类型授权，仍按普通策略重复拒绝或再次询问。
related: [ap-0245, ap-0242, tech-docs/durable-effect-claim-and-ledger-identity]
sedimentation_schema: 2
problem_type: intent-drift
evidence_status: verified
---

# 0247 — 人工 Allow 未被消费，执行层再次决策

- **平台**：跨宿主 Agent 权限控制面

## 问题原型

受保护动作已经通过宿主原生界面展示了可读决策卡，人也明确选择 Allow。期望是该决定被转换成
一次性、范围精确的执行权；实际却只留下“用户同意过”的观察，常规策略随后从头判定并再次拒绝，
甚至要求重复授权。人已经介入，系统仍表现得像从未收到决定。

## ❌ 错误

- 把按钮点击只记作聊天上下文、遥测或布尔标志，不生成可消费 receipt。
- 先运行常规策略，再尝试匹配人工授权；常规策略的 deny 永远抢在 grant 之前。
- grant 只绑定“允许写”，不绑定决策卡、目标、效果、会话、世界状态和使用次数。
- 每个下游工具重新询问同一决定，或把一次 Allow 扩大成永久白名单。

## 为什么错

人工决定与普通策略是两种不同权限来源。Allow 只有在成为强类型、一次性、可 CAS 消费的策略
输入后才有执行语义；“人同意过”不是权限模型。已验证的故障表现是原生 Allow 成功落账，但
后续 PreTool 仍按未授权路径拒绝。相反，grant 在常规策略前匹配且消费后，原动作只执行一次，
重复调用和目标漂移均被拒绝。已排除“给 Agent 全局 do-anything”方案：它失去最小范围和重放边界。

## 适用边界

- 适用于当前宿主的真实原生决定，且 card、provider、session、target 和世界状态仍匹配。
- 不适用于普通聊天中的“继续/授权”、复制摘要、超时沉默或来自另一会话的点击。
- 不可变安全底线仍可拒绝，例如秘密外发、目标替换、破坏性效果升级或资源身份漂移。
- grant 已消费、过期、被替代或范围改变时，应返回结构化原因，而不是静默重问。

## 判定样本

### 路由正例

- **输入**：当前会话 PermissionRequest 原生卡已 Allow，同一目标的下一条命令仍被 PreToolUse
  Hook 报“缺少授权”或再次弹卡。
- **预期**：apply
- **原因**：决定存在但没有进入可消费执行权链。
- **来源**：observed

### 路由反例

- **输入**：人批准写一个本地文件，随后动作改成删除远端数据并被拒绝。
- **预期**：skip
- **原因**：效果和目标已变化，旧 grant 本就不适用。
- **来源**：constructed

### 执行合格例

- **做法或输出**：原生 receipt 生成绑定 card、effect、target、session、epoch、world digest 和一次
  use 的 grant；策略先原子消费 grant，再执行并独立验证；第二次消费返回 already-consumed。
- **预期**：pass
- **原因**：人工决定只授权原动作一次，同时保留安全底线。
- **来源**：observed

### 执行失败例

- **做法或输出**：点击后把 `approved=true` 写进会话，所有写命令永久放行；或执行层继续忽略该值。
- **预期**：fail
- **原因**：前者越权，后者让人工决定失效。
- **来源**：constructed

## ✅ 正确

1. 原生决定产出不可变 receipt，并投影为一次性 HumanGrant。
2. grant 精确绑定可读 card、目标资源、效果分类、provider/session/epoch、世界状态和 verifier。
3. 执行路由先匹配并原子消费 grant，再进入常规策略；不得对同一事实二次决策。
4. 只有不可变安全底线或可读范围真实改变才能再次拒绝，并给出具体差异。
5. 执行成功、失败或未发生都形成终态 receipt；重放不得重新获得执行权。

## 消费与防复发

原生决策桥、GrantBroker、PreTool 策略和恢复通道共同消费。回归覆盖 Allow/Deny、重复消费、
目标/效果/session/epoch 漂移、崩溃恢复及 grant 与常规 deny 的顺序；真实宿主 canary 必须证明一次
点击后原动作执行一次，不能只检查 receipt 文件存在。
