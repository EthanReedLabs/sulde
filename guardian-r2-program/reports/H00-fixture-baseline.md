# H00 fixture 与基线冻结报告

## 结论

R2 的 PARKED → READY 启动门已全部满足，H00 可作为唯一首个 ready task 启动。此结论只
覆盖控制工件、fixture 与基线冻结，不代表 H01-H06 已实施，也不授权安装、生产账本、推送、
dev/main 合并或 Claude 调用。

## 独立回读

- 旧 `guardian-remediation-r97` final-check：`ready=true`，blockers 空；9 accepted、
  4 superseded，没有 ready/running/blocked/open finding；108 evidence 校验零错误。
- `main = dev = origin/main = 0eb4fb6553e652b0352750f4bac24aa6bae746d7`。
- 主仓、dev 与 13 个历史 task worktree 全部干净；没有删除或重建它们。
- 新 worktree 由 `agent-runtime.py provision` 从精确 dev commit 创建，分支为
  `task/r2-guardian-human-authority-lifeform`。
- 停车方案 SHA-256 为
  `3c648a1904cde11ee05f289d0168601a709da104158fd8b4104129d6061f6046`。
- 当前会话 revision 152 通过原生 PermissionRequest 应用，receipt 为
  `9e17eb2da9173b0e76bc7a9548b1ad0a869b1ae2faadb39952fa6d8b03a70805`。

## 冻结基线

- Codex：0.149.1；SessionStart adapter 指向 installed `20260826044342` runtime，healthy。
- 主机：macOS 26.3（25D125），Darwin 25.3.0，arm64。
- generation：
  `0.2.5+codex.20260826044342:b4364153e75ccd5c0a881cf95ed0f3b9ccd40521a574c43fe08bc37eaa579247`。
- 正式隔离基线：423/423 pass，88.896 秒，production write guard clear。
- Claude live：deferred/unknown；不得用静态测试或 Codex 观察替代。
- incident fixture：I01-I19 共 19 项，另冻结 13 个 failure axes。

## 本轮新鲜反样本

1. 相对 `mkdir` 即使 tool workdir 在获准 worktree，仍被归因到主 workspace；使用同范围绝对
   target 才放行。该形状进入 I09/I19。
2. 直接系统 Python 基线包含不存在模块选择器，且缺 PyYAML 触发 legacy no-op；正式 runner
   重跑全绿。该结果只用于测试入口反样本，不是产品 finding。
3. 源码侧 launcher verify 未带 `-B`，在 task worktree 生成 `scripts/kb/__pycache__`，使源码
   fingerprint degraded；installed runtime 与六个 launcher target 未漂移。由于当前授权禁止
   destructive，本轮不删除，作为 I12 的 generated-artifact debt 留给密封 repair 验收。

## 任务图与评审边界

- append-only R2 program 已注册 H00-H06；H00→H01→H02，之后 H03/H04/H05 可并行，H06
  显式依赖全部前置。
- H03/H04/H05 owned paths 无重叠；任何扩张必须先形成 finding 和新可读差异。
- 独立 reviewer 固定为 `guardian-r2-independent-reviewer`，不得由 worker 自报代替。
- H06 必须保留 `Codex accepted / Claude live deferred`，直到真实 Claude 证据出现；program
  manifest 的 `allow_human_deferred=false` 会阻止提前 complete。

## 沉淀候选

- **问题语境**：工具层忽略 workdir 会把合法相对路径归到错误 workspace；源码健康探针未
  强制 no-bytecode 会自己制造待检测漂移。
- **证据状态**：confirmed；两项均在 2026-08-26 当前 worktree 真实复现，且无生产写入。
- **路由正样本**：canonical absolute target；受支持隔离 runner；所有 Python 健康探针带
  `-B` 或 sealed no-bytecode launcher。
- **路由反样本**：只按 contract workspace 解析相对 target；健康探针导入后再测 immutable tree。
