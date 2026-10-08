---
assignee: existing-dev-session
branch: task/predictive-verification-recovery-20260928
capability_tier: deep
---

# 后续任务：集中复核正常对照，并补齐 B1/B2 有效验证

## 工作区与授权

沿用原 Dev 会话、当前宿主配置及本 worktree，不重开任务分支：
`/Users/eric/ClaudePlugin/sulde-pro/.worktrees/predictive-verification-recovery-20260928`。
reviewed HEAD：33851d4（本任务文件与再核验记录是协调端预期新增）。
此文件明确续接 VERIFICATION-RECOVERY-TASK 的集中交还点，仅增加测试侧 B1/B2 验证，
不授权修改生产源码、生产账本或权限。旧要求“正常例不过就立即交还”改为授权内连续修夹具。

允许：tests/test_r3_injection_baseline_r2.py、tests/test_r3_normal_pair.py、
tests/test_r3_real_entry_chain.py、必要的专用测试 helper、本目录任务报告/STATUS。
不改 scripts/、其他 Skill 规则、安装缓存。模型调用预算 0；不跑全量。
禁止合并、推送、安装、删真实资源或处理历史债务。

## 已核实依据与独立性

协调端上一轮是 9f23fa2/194fa6b/33851d4 的实现者，本次再核验不是独立 accepted。
由未编写这些提交的原 Dev 先做集中复核：目标范围、双版本身份、消费断言、持久证据、
规则五文件摘要及历史更正。复核结果单列，不用后续自己编写的测试自批整个候选。
读 VERIFICATION-RECOVERY-REPORT.md 和 REVIEW-CHECKPOINT.md。

正常对照当前复跑 3/3（14.650s）；Optimus normal 清单 205 项回读通过。
已验证输入未变时复用这份证据，不再重新搭 control root 或重跑整个正常矩阵。
被测源码：old=fcd28a4b93f7d63df6b3e0445ea538e48e51c8c3；
candidate=5a2d951a50cea246d52cbc827e0ef63c0053fd7e，与当前 scripts/ 等价。

旧 test_r3_injection_baseline_r2 三项实测：正常例 FAIL（provider 未产合规报告）；
B2 ERROR（registry 未定义，且根本没有待反馈工件）；B1 表面 OK，但只检查空 consumed，
未证明存在 pending request、发生 BrokenPipe 或产生 send_unconfirmed，是无效绿测。
本轮修复这些原测试，不跳过、不删除后声称通过，不新增重复的一套 WIP 脚本。

## 顺序：一次执行到集中交还

### 1. 复用正常夹具和双版本驱动

从 _Chain 创建合规 brief、预测、源反馈、正式 retry；统一 source root 与新进程隔离。
改共享 helper 时运行其四项原回归。不得把两个源码版本同时导入一个 sys.modules。
保持相同配置、输入与断言；原有正常双版本结果是前置，不是 B1/B2 的替代证据。

### 2. B1：发送失败确实发生且走实际生产接线

先用实际首 attempt 生成合法反馈，保存 exact request/来源身份/工件摘要。
经过真实 run_task → monitor_process → 该版本原回调接线，不直接调用修好的回调代替入口。
仅在进程/管道边界注入失败，不替换 run_task、monitor_process、回调工厂或消费函数。
采用有界同步握手等确定性方式证明 provider 已关闭 stdin，再触发写入失败；
不得把“瞬时退出 + 大 prompt 可能 EPIPE”当确定性证据，禁止随机 sleep/盲增 timeout。
若使用入口测试包装器实施边界注入，记录其注入位置与范围，不冒充未插桩宿主 CLI。

断言必须非空且绑定 exact request：实际发送错误、对应账本失败字段、
send_unconfirmed 在册、consumed 不含该 request、原反馈工件存在且身份未变。
同时保留正常发送配对；任务失败若来自报告/导入/身份前置，不计为目标缺陷。
不以预测反馈“已生成”证明“发送失败”。

### 3. B2：同一未确认请求的阻断与显式恢复

候选优先消费 B1 真实留下的状态，而不是造空工件后断言 None。
未恢复时，load 应以明确 send-uncertain 原因拒投；实际下一 attempt 的 stdin 不含反馈事实，
exact request 仍未消费、工件保留。避免普通重放未启动 provider 却被算作“未投递”。
通过候选已有 mark_feedback_recovered 入口对合成状态作显式恢复，然后正式 retry：
stdin 含对应事实、exact request 绑定新消费 run、独立探针通过；无关任务工件不受影响。
该函数只有局部调用接口，未证明生产 launcher 人工恢复接线；不得扩大为生产恢复能力验收。
旧版本无此恢复函数时不得伪造函数；同输入验证其未恢复门控，明确“恢复 API 不存在”。

### 4. 双版本结论与有界验证

先记录各版本实际行为再定性：旧缺陷、候选修复、共同正确、候选回归、无效测试、未测。
旧 agent-runtime 的 lambda 丢 send_failed、候选直接传回调，以及候选新增 load 门控
是代码差异线索，不替代实际失败证据。禁止预设所有场景都必须旧红新绿。
生产候选若未满足不变量，保存有效最小反例并标明产品阻塞，不放宽测试、不擅改 scripts/。
只运行最小注入矩阵 → 实际入口 → 受影响反馈/运行模块；正常输入等价可复用。

## 成本、证据、停止线

零真实模型。每个子进程有上限；同一失败两次无新证据就改变诊断方法。
普通夹具失败、阶段通过或上下文续接不交还等“下一步”；保存检查点继续原任务。
需要生产修改/额外权限/外部条件，或诊断换法仍无安全进展时才准确交还。

普通测试只写临时目录。正式证据在 Optimus：
`/Volumes/Optimus/Sulde/tasks/predictive-execution/injection-verification/<新唯一目录>/`。
保存源码/测试/配置身份、同步握手与错误事实、各 attempt 命令/输出/返回码、
工件/消费与恢复前后状态、探针和排除前置失败的依据；清单不含自身并回读校验。
旧目录不覆盖，不采集用户真实数据/密钥。挂载或权限不足准确披露，不偷偷换盘。

完成后仅提交此任务分支，集中报告：前一交付的独立复核、B1、B2、正常配对、
代码实际修改范围、成本、证据与未验收边界。只标 candidate-awaiting-independent-review，
不能自批新测试。真实 Agent、A 的 C 层、历史债务、多样本、发布安装继续独立待办。
