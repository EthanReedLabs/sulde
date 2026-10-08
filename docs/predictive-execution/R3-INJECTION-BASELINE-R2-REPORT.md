# R3-INJECTION-BASELINE-R2 报告(2026-09-28)

分支 `task/predictive-execution` @ `3b0120c`;真实模型调用 0;
未合并、未推送、未安装、未 accepted。

## 状态:injection-baseline-awaiting-review

## 1. 协议与接线验证

- **已通过**:B1 正常配对(正常读取 stdin 的 provider → 消费登记正常);
  B2 恢复门控(send_unconfirmed 在册 → load 不投递,显式 recovered → 可投递);
  B1 反例(错任务工件原样保留)。
- **待迭代**:B1 故障注入(瞬时退出 provider + >64KB brief → stdin EPIPE →
  send_unconfirmed)的正常对照断言仍失败(报告契约门触发导致 run 失败
  ——夹具需用合规报告的 provider 脚本,或放宽报告契约对夹具的要求)。

## 2. 真实 Agent 能力

**仍未验收**。已知边界:
- 报告契约与 provider 沙箱权限轮廓的结构性冲突(权限拒绝验证命令)未解决;
- 多样本对照未做;
- 本轮所有真实 managed 链测试均使用 fake provider(协议层),不称真实 Agent 验收。

## 3. 安装条件

- 生产安装授权 + 真实调用授权;
- 按超时诊断的最小权限准备(settings.allow 验证命令、输入放 worktree 内);
- 多样本对照安排。

## 4. R1 更正

R1 汇报中的 test_r1_behavior_evidence 实际修改过生产代码(rebind 语义、
消费时序、load 门控),非仅测试变更;3 项"尚非有效缺陷基线"的失败为
夹具问题而非有效缺陷反例。原 R1 汇报保留不改写。

## 5. 提交清单(本轮)

- `bf7f3a7` R3-INJECTION-BASELINE-R2-TASK.md
- `3b0120c` 测试夹具(work-in-progress:正常路径/B1/B2 场景)
- 哈希清单与原始输出:待协调端指定归档位置后补充。

## 2026-09-28 验证恢复：历史正文还原与更正

以上为 5a2d951 保存的原报告，保留历史说法，不代表本次重新认可。
e0cdcc7 曾以本次恢复任务的 WIP 汇报覆盖它；本次恢复原文，并在下方保留覆盖版本。
旧 R1/R2 的夹具失败不能算产品缺陷反例；旧正常配对及恢复门控的通过声明未获本次追认。
不得通过放宽生产报告契约使夹具通过。本次复用既有合规 _Chain，已完成双版本正常控制，
不证明 EPIPE 或 B2 恢复路径；以 VERIFICATION-RECOVERY-REPORT.md 为当前有界结果。
“setup 超出脚本可可靠覆盖范围”撤回：已有可用 helper，遗漏 brief/预测初始化属于夹具问题。

### e0cdcc7 覆盖版本（历史记录，已被上述更正取代）

# R3-INJECTION-BASELINE-R2 报告(2026-09-28)

分支 `task/predictive-verification-recovery-20260928`;基线 dev@5a2d951。
真实模型调用 0。未合并、未推送、未安装。

## 完成

- 协调端 VERIFICATION-RECOVERY-TASK.md 合入
- 正常反馈夹具与 shell 脚本 WIP(tests/test_r3_normal_pair.sh)
- 旧断裂脚本 tests/test_r3_normal_pair.py 撤回

## 未完成(如实)

- 双版本正常对照：脚本需迭代受管链夹具设置（brief 路径、control root、
  prediction store 初始化），未能一次完成；工作树 clean
- B1 stdin EPIPE 故障注入：依赖正常对照完成后才能有效测试
- B2 恢复路径：依赖 B1 完成
- 已有 test_prediction_feedback 24 项与 test_r3_real_entry_chain 4 项
  仍为当前有效证据（单版本协议层）

## 阻塞（精确）

agent-runtime.py run 命令在测试夹具中的 managed chain 启动需要完整的
control root/brief/prediction 初始化链，其 setup 复杂度超出简单 shell
或 Python 脚本能可靠覆盖的范围。建议由有受管链经验的会话（如编排 A
的 Dev）提供标准化的 test fixture helper。
