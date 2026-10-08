/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06I-R2-interruption-authority.json
执行任务SHA256:55ebd49197d5c940394fd405224b2814d28b290a81e3cd481c4c5d4bcac377c2

# H06I-R2 — final review repair for FR2-009..013

## 权威与范围

- 这是同一 `H06I-R2-interruption-authority` 的 Amendment-004 单次修复，不是新任务。输入候选为当前 full clone 中的冻结红证据；禁止从旧候选复制、重建计划或删除工件。
- 行为代码只能修改 `scripts/kb/agent-runtime.py` 与 `tests/test_agent_runtime.py`；报告只能修正 `guardian-r2-program/reports/H06I-R2-interruption-authority.md`。`scripts/kb/native_agent_broker.py` 与 `tests/test_native_agent_broker.py` 必须分别保持 SHA-256 `0393e1bb5c2cee278f06eb3c2ca2a068aba481cff82beacb28ae0205a0af39c7`、`0ed8ced54a46fe6fbcbb1ee746aa6dec33692ba1ef644d1d4d38bce679f88850`。
- 不安装、不写生产 descriptor、不改 scheduler、不提交、不合并、不推送、不启动 H06J。失败即停，不自动重试、不创建后继任务。

## 必须闭合的五项根因

1. `FR2-H06I-R2-009`：在 `RunHandle.settle` 之前规范化 production Codex final bytes，使 run ledger output、`.last.md`、durable report、receipt output/report summaries 真正绑定相同 bytes；禁止先记 raw 18541B、后写 canonical 18542B。
2. `FR2-H06I-R2-010`：读取入口必须把 lexical root 的 `lstat` 身份与实际 opened root dirfd 的 `fstat` 身份绑定，并在返回前验证 pathname/父链仍指向同一 inode。canonical writer 必须使用 descriptor-relative 临时文件、fsync、rename 与 readback；任何 root/parent/symlink swap 都必须在外部写发生前失败。覆盖读取 root swap、写入 parent swap、写后替换和 durable report 替换攻击。
3. `FR2-H06I-R2-011`：区分 provider natural completion 与 `paused/awaiting_human/timeout` local interruption。只有自然完成要求 output-last-message 与 durable report；获 H06H 授权的 local interruption 可以 output absent，仍须通过 exact ledger interruption evidence、broker receipt 与 quiescence，且用真实 `provider=codex,test_mode=false` 测试。
4. `FR2-H06I-R2-012`：修复 macOS `/var/folders` 与 `/private/var/folders` lexical/resolved identity混用。路径身份必须在单一规范层比较；完整测试矩阵既要在普通默认 TMPDIR 下通过，也要在显式 `/private/tmp` 对照下通过，不得靠受管 wrapper 注入掩盖。
5. `FR2-H06I-R2-013`：报告中同一命令只能有一个 current-success claim，并必须绑定 candidate SHA-256、execution binding、环境身份、命令身份、exit 与计数。validator 必须拒绝重复命令、冲突计数、缺绑定声明。删除或改写旧的冲突成功投影，但保留历史 finding、失败尝试和恢复事实；不得把本阶段或后续自托管提前写成通过。

## 实现与测试纪律

- 先复现五个红样本，再用原生 patch 修改；不得用 shell 重定向、脚本批量改写或临时旁路。
- 测试至少覆盖：canonical ledger equality；output-last 缺失/symlink/non-file/hardlink/oversize/invalid UTF-8/empty/ctime drift；root dirfd swap；writer 外部逃逸；写后替换；真实 production local interruption；默认 macOS TMPDIR；显式 `/private/tmp`；broker hostile reason/type/order/quiescence 既有矩阵；报告重复/冲突/缺绑定拒绝。
- 运行 focused、`tests/test_agent_runtime.py`、冻结的 `tests/test_native_agent_broker.py`、combined、fresh no-hardlink full clone。默认环境和显式 private temp 对照必须分别记录，条件 skip 必须说明原因。
- worker 只提交候选代码、测试与报告证据，不得自行生成 Stage boundary 或宣称 accepted/integrated/H06J/R2 complete。

## 报告约束

- 仍且仅保留一次 `## 结果`、`## 过程`、`## 遇到的问题`、`## 解决方式`、`## 遗留风险与建议`。
- `## 结果` 只保留这一 candidate 的唯一 current evidence set；旧 run 的测试数字只能作为明确标注的历史失败事实出现在问题段，不能作为 current success。
- 逐项写明 `FR2-H06I-R2-009..013` 的红证据、代码根因、绿色用例和未越过的生产边界。

## 沉淀候选

- 若确认新的通用根因，只在报告中形成 Layer1 问题卡候选，不直接写跨项目知识库。
