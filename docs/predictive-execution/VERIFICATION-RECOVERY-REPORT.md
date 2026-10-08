# 验证交付恢复与连续派单规则集成

状态：candidate-awaiting-independent-review。执行者接手停止的 Dev 任务，不自行 accepted。
分支：task/predictive-verification-recovery-20260928；接手 HEAD e0cdcc72d2ac211db95bd4586331aa95410c5f5c。
测试修复提交：9f23fa2。未合并、推送、安装或调用真实模型。
规则集成提交：194fa6b；最终报告提交可由本文件 Git 历史定位，避免自引用提交摘要。

## A. 本次真正验证了什么

同一驱动与既有 `_Chain` 夹具，分别在新进程、git archive 源码根、临时工作仓库及
隔离 SULDE_HOME/SULDE_KB_DATA_ROOT 执行；整个链使用 -B/禁写字节码。
不是另建生产 fixture 系统，更没有修改 control root 解析或放宽报告契约。

| 被测版本 | 精确提交 | 无反馈正常例 | 反馈正式续接 |
|---|---|---|---|
| old | fcd28a4b93f7d63df6b3e0445ea538e48e51c8c3 | 通过 | 通过 |
| candidate | 5a2d951a50cea246d52cbc827e0ef63c0053fd7e | 通过 | 通过 |

`git diff af3a614 5a2d951 -- scripts/` 为空，冻结候选生产源码等价。
每侧记录三个实际导入模块路径与 SHA256；子进程必须从对应提取树导入。
共享 helper 唯一改动是可指定测试源码根，默认仍为原仓库；消费者原四项回归通过。

正常送达首 attempt 的失败是合成反馈准备，不是旧缺陷反例。保存发送前源工件，
实际 provider stdin 必须含其 verdict 与全部 facts；exact request 消费记录绑定
实际 consuming run/session，来源与消费不同；送达事件的 request/prediction 对应且
无 send_failed。任务 status 必须 success、rc=0，不能只采信 provider 的模拟报告。
独立执行 consumer.py 必须 exit 0、输出 ok 2。工件已消费且不残留。

工具负控只在测试进程内移除观察结果中的 exact consumption fact，不改产品账本。
两版本均以 missing exact consumption fact 返回 1，汇总 passed=false；这是验证器负例，
不是对 EPIPE 的注入，不证明旧缺陷或候选修复。

## 命令、结果与持久证据

证据根：`/Volumes/Optimus/Sulde/tasks/predictive-execution/R3-normal-pair/20260928T111000-recovery/`。
运行目录为本任务 worktree；以下命令均设置 PYTHONDONTWRITEBYTECODE=1。

- `python3 -B tests/test_r3_normal_pair.py --evidence-dir <证据根>/normal`：exit 0，两侧 worker exit 0。
- `python3 -B tests/test_r3_normal_pair.py --missing-fact --evidence-dir <证据根>/negative`：预期 exit 1，两侧 worker exit 1，原因均为消费事实缺失。
- `python3 -B -m unittest tests.test_r3_normal_pair -v`：3/3，14.494s；随后增加送达事件 request/prediction 精确关联断言，以上正式归档已包含并通过。
- 最终相同套件以 `-q` 复验：3/3，14.884s（绑定 9f23fa2 测试内容）；未重跑全量。
- `python3 -B -m unittest tests.test_r3_real_entry_chain tests.test_prediction_feedback tests.test_model_dispatch_contract tests.test_runtime_provider -q`：62/62，6.525s。
- 官方 quick_validate（现有含 PyYAML 的 KB venv）：dispatch-task / writing-task-md 通过；assign 因基线已有 user-invocable 失败，保留兼容元数据，不为凑绿删除。
- 未跑全量：只有测试、说明与指令层变更，生产源码和解析器不变；影响范围与预估一致。

归档包括命令、stdout/stderr、返回码、实际模块路径/摘要、合成 stdin、运行与消费账本、
独立探针、驱动及 helper 副本。normal 清单 205 项、negative 197 项，均用
`shasum -a 256 -c sha256.txt` 独立回读 exit 0，清单不含自身，旧证据未覆盖。

| 工件 | SHA256 |
|---|---|
| driver | 233215f8ddee57baefcfb38c68a9e53d3a625e5cedde188496b700e86b7cd97d |
| fixture | 2406bf510caaa096abfefe167fbe579a9f8786ea10395ebf00472de385b2a28d |
| normal/sha256.txt | 9fb296e2d4f243d43cee9e8d2000599c495dc4588b953053d3915d022b0324d8 |
| negative/sha256.txt | 1f3cc47db4ab85ebeb6abe27aa8c103c42a8a5113140cd83be9350019e9d7876 |

普通 unittest 只写 TemporaryDirectory；正式归档必须显式指定全新目录，已存在即拒绝。
原模拟报告只是协议输入，探针输出才是本轮合成最终行为证据。无真实用户 prompt/密钥采集。

## B. 更正与过程失败

保留并更正 R3-NORMAL-PAIR-REPORT、STATUS。恢复被 e0cdcc7 覆盖的历史 R2 正文，
同时保留覆盖版本并注明已取代。撤回“setup 超出脚本可可靠覆盖范围”：已有可运行
helper；5c1f9d7 未创建 brief/未初始化预测，shell WIP 还未实际执行受管链。
不能把前置失败归为产品缺陷，也不能据此证明两版本相同。旧 4/4、删除脚本、提交或推送
不构成双版本验收；旧 R1/R2 无效基线不因本轮通过自动转正。

接手后驱动曾错误把文本 .status 当 JSON，随后曾按未排序 glob 拼接前后 run 账本。
均为本轮测试工具缺陷：改读 status 文本和 guardian JSON，并沿用已有夹具的有序回合读取；
完整诊断输出曾保留于 /private/tmp/sulde-pair-diagnostic-20260928-a（临时，非正式证据）。
未放宽目标断言；原失败在协调会话中保留。正式归档只描述修正后的实际运行，不重造旧日志。

## C. 派单规则

五项文件与只读源 worktree 的已冻结 SHA256 全部相同，详见 docs/dispatch-continuous-execution.md。
落实一次冻结目标/范围/预算、授权内连续执行、两次无新证据换方法、按影响验证、
集中独立复核、相邻问题不自动扩大范围。未改运行时、审批、模型配置或安装缓存。
规则长任务行为未实测，源码集成不等于已安装全局生效。

## 边界与沉淀候选

本次完成 A/B/C 有界交付，仍需独立复核。EPIPE/B2、真实 Agent 行为、生产权限链、
历史债务、A 的 C 层、Windows、多样本和资源清理未验收，不作为本次测试修复的新增门槛。
真实模型调用 0；执行总 Token 未计量，unknown；没有声称成本收益已测得。

沉淀候选（verified，仅限上述合成测试链）：先复用真实可运行夹具再定位首个失败前置。
路由正例：缺 brief/预测先修夹具；反例：未进入目标代码却立项生产解析修复。
执行正例：同驱动双源码根、exact request 事实与独立探针；反例：固定 return 0、
零执行或只凭报告标题判通过。证据为本报告所列归档；未写正式知识库/记忆。
