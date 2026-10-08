# LLM 失败诊断修复：本地验收报告

日期：2026-09-23。最新状态：修复提交 `898906a` 已合入 dev，本地打包产物验证通过；
未推送或安装。最新交付事实见 [DELIVERY.md](DELIVERY.md)；下文保留前序审查边界。

最新集成审查：两项遗漏已补齐，82 pass / 2 Windows skip，独立合成检查 44/44。
详见 [INTEGRATION-REVIEW.md](INTEGRATION-REVIEW.md)。初轮证据保留，不代表当前源码摘要。

用户选择先修复真实问题，暂停 Orca/Sulde 对照环境扩建。本次结果不是双方 Harness
对照成绩，也不包含 Token 或生产性能收益结论。

## 基线与范围

- 基于 dev `364ad3076bf29e92d44c06036a520303161b449e`。
- 分支 `task/llm-failure-diagnostics-20260923`，独立任务 worktree。
- Guardian revision 5 原生批准初轮修复；revision 6 原生批准集成补齐，新增 scheduler
  最小启动 fixture 的精确路径，仍限定诊断修复、测试与任务报告。
- main/dev、生产知识库、记忆、运行配置、调度器均未修改。
- 使用任务续接、意图守卫与知识检索技能；KB ap-0178 指导统一安全输出，
  ap-0224 指导真实受限执行环境与正反例，未直接写入正式知识库。

## 根因与修复

原入口将失败 stderr/stdout 的前 500 字符拼入异常：长 banner 会遮住真正原因，
原始输出还会经异常、日志、repair queue 传播。启动/解析异常链也可能保留命令或正文。
旧回归未覆盖这些情况；独立基线 44 个检查中 22 个失败。

1. 新增纯标准库 `scripts/kb/llm_diagnostics.py`，两个入口共用。
2. 固定类别 quota / timeout / startup_failure / invalid_output / unknown。
   仅识别有限结构化错误码或明确错误行；引用、提示词回显、矛盾与无法识别内容保留 unknown。
3. 非零退出诊断优先 stderr，仅 stderr 为空时使用 stdout；最多扫描 8192 字符的
   完整首尾行，长内容明确标记 scan=truncated。输出固定字段、数值事实与建议，
   不复制原始失败正文，摘要限制 1024 字节。
4. TimeoutExpired/OSError 诊断不保留原始异常链；JSON schema 错误不向公开异常
   保留 JSONDecodeError.doc。schema/brief 校验输出固定 invalid_output 信息。
5. 成功 stdout、既有重试次数、失败 watermark、成功回执语义不变；
   分类不参与权限判断，也不新增重试、模型调用或修复 Agent 启动。

## 验证与证据

最新证据：[fix-checks-v8ecbs2w.json](fix-checks-v8ecbs2w.json)。记录基线提交、源码及
测试 SHA-256、退出码、耗时、输出摘要、独立检查结果。首轮失败证据
[fix-checks-1aj0ax29.json](fix-checks-1aj0ax29.json) 保留：发现 quoted user prompt
未完整排除，修复后复验通过，未覆盖旧记录。初轮通过记录为
[fix-checks-nl4mc3qq.json](fix-checks-nl4mc3qq.json)。集成补齐前反例证据为
[fix-checks-1mcnt1_u.json](fix-checks-1mcnt1_u.json)。

| 测试模块 | 通过 | 跳过 |
| --- | ---: | ---: |
| test_llm_diagnostics.py | 17 | 0 |
| test_distill_conflict_resilience.py | 10 | 0 |
| test_self_repair.py | 35 | 0 |
| test_auto_distill_windows.py | 9 | 2 |
| test_command_template_split.py | 8 | 0 |
| test_scheduler_entrypoints.py | 3 | 0 |
| 合计 | 82 | 2 |

两项跳过要求原生 Windows PowerShell，本机未代替 Windows 验收。
另有独立合成验收 **44/44 通过**，相同基线原为 22/44 通过。
覆盖真实 fake-LLM 子进程失败、秘密/路径/URL 哨兵、长 banner、引用与冲突、
成功输出、实际调用次数，以及隔离 main 日志/watermark 和 repair queue。
TimeoutExpired 在 subprocess 边界注入，不宣称真实服务商超时测试。

所有验证使用拒绝网络、仅任务临时目录可写的 Seatbelt；未调用真实模型。
这里的 model_calls=0 仅指试验/测试调用，不代表协调会话没有 Token 开销。
运行器与 profile 为本机任务证据工具，依赖已保留的 pilot 验收器，不是通用 CI 入口。
可移植单测入口为 `python -B -m unittest discover -s tests -p test_llm_diagnostics.py -q`。

## 验收边界与剩余事项

- 独立证据中的 final_acceptance=false 有意保留：它是部分矩阵，不是完整 Harness
  对照或生产发布验收。上述通过数不能替代安装、真实宿主或全平台结果。
- 完整 annotation/backfill 外部链未运行；隔离状态与现有回归证明本次未改相应成功/
  失败语义，不能宣称外部链已 live 验收。
- 诊断采用有限白名单，不保证识别所有服务商格式；未知格式安全降为 unknown。
- 失败摘要有界，但原有 capture_output 仍在内存捕获完整输出；流式容量限制不在本次范围。
- 未新增原始诊断持久证据库；既有日志/队列保留策略未改，因此没有新增原始证据 TTL
  清理任务。报告仅含合成样本结果和摘要，不持久化秘密或原始失败正文。
- 未运行全量测试或安装。初轮发现打包器从 Git 跟踪清单选择 `scripts/kb/`；
  helper 当时未跟踪，不能只提交旧文件 diff。该项现已通过整体提交和实际产物
  摘要/启动验收关闭，详见交付报告。
- Orca 环境保持暂停，没有启动 runtime/daemon 或扩建另一套运行环境。

集成自审、补齐、提交、dev 合入及本地打包验收已完成（不是另一 Agent 的独立复核）。
后续正式安装需要独立批准与发布验收；当前不能报告生产已修复。

## 沉淀候选（未入库）

标题：LLM 命令失败不得用原始输出前缀充当诊断摘要。

- 语境：自动蒸馏与自修复调用命令失败，需要能定位类别，又不把提示词/秘密传播至日志。
- 证据状态：verified（本次合成故障与源码链）；服务商真实格式覆盖仍 inconclusive。
- 根因：两个入口各自截取原始 stderr/stdout，缺少安全汇总边界；原始异常上下文可携带正文。
- 处理与结果：共享最小化诊断，保持业务控制行为；基线 22 项失败变为独立 44/44 通过。
- 路由正例：长 banner 后有明确 error code，且错误前缀可能包含敏感内容。
- 路由反例：成功业务输出中出现 quota 单词，不能据此判定失败。
- 执行正例：白名单类别、固定建议、长度/退出事实；保留 unknown 并验证全部失败输出通路。
- 执行反例：复制原始前 500 字符、把提示词中的错误引用当运行事实，或修复诊断时推进失败水位。
- 来源：本报告、最终 evidence、四个实现/测试文件的固定 SHA-256；协调端后续判重入库。
