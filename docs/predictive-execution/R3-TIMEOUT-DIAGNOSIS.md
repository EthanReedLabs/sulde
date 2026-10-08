# R3 真实运行超时诊断(基于归档证据,未启动真实模型)

归档:`/Volumes/Optimus/Sulde/tasks/predictive-execution/R3/20260927T155208-DC9D7F79/repo/.codex-agent/`

## 第一性事实

| 项 | r3fix | r3fix2 |
|---|---|---|
| status | timeout | timeout |
| rc / duration | 143 / 240s | 143 / 240s |
| stop | timeout | timeout |
| r3fix*.last.md | **0 字节** | **0 字节** |
| events.jsonl | 4853 行(985KB) | 5533 行(1.2MB) |
| 事件类型 | system 4805 / assistant 32 / user 16 | system 5471 / assistant 37 / user 25 |
| result 事件 | **0** | **0** |
| 末尾事件 | tool_use Bash | tool_use Bash/Read |

## 三分判定

1. **provider 未完成 —— 成立**。真实 claude 在 240s 超时点仍处于工具调用执行中
   (末尾事件为 tool_use),从未产出 final message;SIGTERM(rc=143)为运行器
   超时处置,产物 .last.md 为零字节属 fail-closed 正确行为。
2. 输出读取/结算异常 —— 排除。事件流完整落盘(4853/5533 行),游标推进正常,
   结算读取正常(读取到的就是"无 final message")。
3. 有输出但格式不合规 —— **排除/撤回**。报告为零字节,不存在"格式不合规的
   输出";此前 R3-REPORT 中"必须在 provider 命令层结构化保证格式"的确定性
   归因**撤回**:agent 的最终回复内容如何,在 provider 未完成的前提下
   inconclusive。

## 根因与归因更正

240s 为本次运行的启动参数选择(`--timeout 240`),对真实 claude(沙箱 bash +
逐事件监督)明显不足;产品对超时的处置(fail-closed、零字节报告、rc 143)
本身正确。**更正**:R3-04 的失败并非"Agent 两次未遵循报告格式",而是
"Agent 未能在超时窗口内完成"。给足超时后的行为 inconclusive。

## 最小后续(登记,不实施)

- 重跑时使用足够 timeout(如 900s)或结构化输出模式,观察真实最终回复是否
  满足报告契约;
- 事件流中 system 事件占比 >97%(本任务两次运行 ~1MB),可登记为日志体积
  优化候选项。


---

# 追加:permission_denied 配对分析(R3-closeout,2026-09-28)

对两次归档事件流按 system.permission_denied 与 tool_result(is_error) 配对:

## r3fix(3 次拒绝)

| # | tool_use_id | 命令 | 拒绝原因 |
|---|---|---|---|
| 1 | call_75c10ffb… | Bash: + echo exit 组合 | 子命令需审批(multi-op) |
| 2 | call_4653af1a… | Bash(验证类命令) | requires approval |
| 3 | call_6557e5ec… | Bash(验证类命令) | requires approval |

## r3fix2(4 次拒绝)

| # | tool_use_id | 命令 | 拒绝原因 |
|---|---|---|---|
| 1 | call_cac2f335… | Bash:(读工作目录外文件) | multi-op/需审批 |
| 2-4 | call_fb1c3dde… / call_77594a36… / call_ed668f7f… | Read:frozen-task.md、attempt1.out、attempt2.err | workingDir(工作目录外) |

## 修正后的归因

- 数值修复在早期已完成且正确(探针独立证实 average: 50)。
- 结构性阻塞:**报告契约要求 ✅ 证据行含"实际命令+exit 0",而 provider
  沙箱拒绝了执行验证命令( 组合命令被 multi-op 审批拦截)**
  ——✅ 证据在该权限轮廓下无法产出 → 报告契约必失败,与剩余时间无关。
- attempt 2 的 3 次拒绝均为读取工作目录外的任务文件(冻结任务书/历史输出),
  同样无法满足,但属输入放置错误(应放在 worktree 内),非沙箱缺陷。
- "240s 设置不足"的说法**不成立**:数值修复远早于超时完成;时间消耗在
  被拒绝的重试上。两种表述("240s 内未完成"/"240s 不足")都不如
  "权限轮廓与报告契约结构性冲突"准确。
- 量化贡献:拒绝事件占事件的极小部分,但其阻断的是报告契约的✅证据链,
  属必要条件;与"若未拒绝是否能在 240s 内完成全部报告"的叠加判断
  → **inconclusive**(无反事实运行)。

## 下次真实验收的最小权限/输入准备(本轮不实施)

1. 任务 settings 的 permissions.allow 预置只读验证命令
   (如 `Bash(python app.py)`)或以监督端探针输出替代执行者自证 ✅;
2. 冻结任务书与全部输入放入 worktree 内(.codex-agent/),不放外接盘;
3. timeout 240s 可保留(非根因);不建议为绕过拒绝而放宽沙箱。
