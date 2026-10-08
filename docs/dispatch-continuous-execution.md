# 派单连续执行规则变更

## 范围与状态

2026-09-28，按用户要求将“有界连续执行、集中独立验收”记录到后续 Sulde 派单逻辑。
基线 `dev@f932ca8`；分支 `task/dispatch-continuous-execution`。
本轮仅更新源码规范、Skill 与模板，未改运行时、Guardian、任务解析 schema 或已安装缓存。
未修改 predictive-execution 的任务或代码，未替其宣称验收通过。
未合并、推送或安装；其他会话的旧 Skill 不会因此自动更新。

## 生效入口

- `skills/dispatch-task/SKILL.md`：派单时附带完整执行约定，不逐测试派单。
- `skills/coordinator/writing-task-md/SKILL.md`：协调端冻结范围并集中审查，取消相邻发现自动扩范围。
- `skills/dev/assign/SKILL.md`：接单后按授权连续返修，取消普通验证失败立即交还。
- `spec/task-authoring.md`：宿主中立的完整约定，现有 Claude/Codex staging 清单均已包含。
- `template/_project/docs-hub/00_shared-rules/task-brief.md.template`：新任务显式填写边界、预算与停止线。

这些是 Agent 指令层的执行规则，不是新控制面或机器强制门禁；没有改变 CLI 渲染器。
后续派单经 Skill 将约定写入任务正文。发布后才会更新已安装 Skill，不能宣称本轮已全局生效。

## 核心约定

一次冻结目标/范围/证据/预算，由一个执行端连续做到约定复核点；阶段通过或普通测试失败
不要求用户回复“下一步”。注入任务先保证旧版和候选正常对照有效，再用同一测试区分旧缺陷、
候选修复、候选回归与无效测试，通过后直接进入入口与受影响模块验证。
两次无新证据则改变诊断方法，真正缺权限、外部条件、预算或触及明确停止线才交还。
不可因连续执行扩大权限、覆盖只读/仅测试限制、跳过正式审批、自动安装或付费调用。
文档变更不强加故障注入；不同改动按影响分层测试。协调端集中汇总阻断项，不能为一轮结束而降低标准。

## 验证记录

在任务 worktree 执行，所有 Python 命令均使用 `-B` 和 `PYTHONDONTWRITEBYTECODE=1`。

1. `python3 -B -m unittest tests.test_model_dispatch_contract tests.test_runtime_provider -v`
   → exit 0，28 项通过，unittest 报告耗时 0.920s。
   范围：既有派单契约与提供方回归；不等于新规范已在真实 Agent 长任务中验证。
2. 官方 `skill-creator/scripts/quick_validate.py`：默认 Python 缺少 PyYAML，启动失败；
   未安装新依赖。改用稳定 launcher 声明的现有 `/Users/eric/.sulde/data/kb/venv/bin/python` 后，
   dispatch-task、writing-task-md 均输出 `Skill is valid!`。
3. assign 同一校验器拒绝既有 `user-invocable` frontmatter 字段；本轮 frontmatter 未改，
   基线存在相同字段。保留跨宿主元数据，不为通过 Codex 通用校验删除它。
4. `git diff --check` 通过。未跑全量、未启动模型或生产安装；改动仅为指令和模板正文。

逐条规则人工对照涵盖：正常阶段继续、夹具失败先修夹具、旧红候选绿、两次无进展换方法、
超预算准确交还、范围外另记、明确停止线保留、只读任务不扩权、注入不替代真实 Agent 证明。
这是规范审阅，不是自动化行为评测或独立验收。

验证时文件 SHA256（不含本报告；后续变更应更新记录）：

| 文件 | SHA256 |
|---|---|
| skills/dispatch-task/SKILL.md | b289fe502318dcb137f37247a35fab2a0acb436e6807177e2b507b733462de69 |
| skills/coordinator/writing-task-md/SKILL.md | f34ddf6c6dc29e237d92d4b6688bc7cd4013accd481c694054076555664ea239 |
| skills/dev/assign/SKILL.md | 01f03faeea2e4d0738415b8340d7a02b19f0acfa20caa06c771bd4e007059fc2 |
| spec/task-authoring.md | c5b9c807ffd39fc2bc6e1328568179f1bdb68c42f40ae36fb5527dfe8ffaabb7 |
| template/_project/docs-hub/00_shared-rules/task-brief.md.template | e614479952a789bbbf9a363a4cdfa78a0f1393156ea910af071d93c9ef020afb |

原始工具输出保留于本次协调会话；本文件记录命令、结果和输入摘要，未声称独立归档了原始 stdout。
本次没有因规则更新直接写入正式知识库或记忆。

## 2026-09-28 验证恢复任务集成

以上为源工作树历史记录。本次在 `task/predictive-verification-recovery-20260928`
（集成前 HEAD e0cdcc7）复制五项规则，逐文件 SHA256 与上表完全一致，源工作树未改。
入口/反馈/派单组合回归 62 项通过（含派单两套件）；两份 Skill 校验通过。
assign 校验仍只因基线已有 user-invocable 不在通用校验器词表而失败；未删除该字段。
仅指令层集成，不代表已安装生效或已验证真实长任务行为。未添加运行时门禁。
