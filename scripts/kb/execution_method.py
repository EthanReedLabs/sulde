"""Pure managed-input projection of the existing task-authoring method contract."""


def execution_method_prompt() -> str:
    """No I/O, retries, authority or test execution: instructions only."""
    return """--- Sulde 有界执行方法（不新增权限） ---
原任务的明确停止线、预算、只读/audit-only/tests-only 限制优先；连续执行不扩大授权。
在已授权范围内完成诊断、最小修复与验收；普通阶段通过/测试失败只更新进展，
不等待逐轮“继续”。缺权限、范围决策、外部条件、预算耗尽或用户停止才准确交还。
修复先建立有效正常对照，再以同一夹具/断言区分旧红与候选绿，随后验证真实入口
和受影响模块。文档任务不强加注入；模拟 provider 的协议通过不等于真实 Agent 能力。
同一失败两次无新证据：检查调用可达性、夹具有效性和首个失败前置，改变诊断方法；
不机械重跑、不自动加超时/开新任务、不降低断言。这不是自动重试计数或审批门。
按任务批准的基线使用现有 scripts/kb/test-evidence.py plan --base <批准基线> 做风险选测；
只在任务已授权测试范围内执行 run，不能因推荐测试而擅自执行或扩大权限。
在逻辑边界解释预计/实际影响较大、较小或一致，说明遗漏还是合理简化及证据。
预测差异是 task baseline→worktree 的机械观察，不是本 attempt 独有变化或新增授权；
事实被截断时保持不完整，不宣称 as_predicted。上下文续接保留证据和下一动作。
提交集中独立复核，不自行 accepted；新发现另记，不擅自扩大验收。
"""
