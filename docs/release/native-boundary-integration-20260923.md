# 原生路径边界修复：本地 dev 集成记录

capability_tier: balanced

## 范围

用户要求进入修复后的下一步。当前会话原生决策 revision 20 将范围限定为复核、提交、
快进合入本地 dev、保全私有证据和具备条件的资源收尾。不推送、不安装、不升级 CLI，
不修改 main 已跟踪文件、生产安装、调度、正式知识库、图谱或其他任务工作树。

源任务：`task/native-failure-diagnosis-20260923`；集成前 dev 和任务基线均为
`f5cbf6cde41c35ffb652a360c2f558a66e1c0c4c`。
main 保持 `43be088f0f1234573af5a4c8bfe90df6f0d5aea2`。

## 复核与测试复用

回读 [修复报告](native-boundary-repair-20260923.md)、源码差异、新增测试及运行器。
修复源码、已修改测试及相关调用方测试共 10 份文件与成功测试元数据中的 SHA-256 一致；
完整日志摘要与 run.json 一致，JUnit 无 failure/error/skip。

- boundary：46 passed、30 subtests passed。
- consumers：15 passed、55 subtests passed。
- 默认临时根 / 独立临时根：三项历史场景各 3 passed，实际拒写负例保留。

本轮不重跑上述测试。提交前后按工作树 → index → commit tree → dev 检出字节逐层核验，
只有相同内容才能复用证据；这不是声称在新 commit 上重新执行了整套测试。
集成仅允许 fast-forward，若 dev 前进或内容变化应停止，不以旧结果覆盖新输入。

## 私有证据保全

最初批准的 `.codex-agent` 归档目标被 Guardian 的受保护工件规则在执行前拒绝，未复制。
经新原生决策明确修订后，改用仓库根私有目录：
`.local-evidence/native-boundary-20260923/raw/`。

- 467 个文件，4,615,347 字节；原始证据和副本逐文件路径/长度/SHA-256 完全一致。
- 对按相对路径排序的 `{path,bytes,sha256}` 数组，使用 JSON sort_keys=true、紧凑分隔符，
  得到清单摘要 `3743c6c3f6b07a208b9dabad185e3a876e18fc4e075a39f35e5c04f8f027c72b`。
- 归档父目录权限 0700；本地 `.gitignore` 排除整个目录内容，已用 git check-ignore 回读。
- 未删除、覆盖或改写任何原始诊断/失败日志；原始数据不进入 Git。

上述证据包含历史失败、修复中首次比较器失败以及最终成功，不能只选择成功记录归档。
提交/集成的实际 commit、内容回读结果及清理状态由同目录的本轮完成回执补充，
不将文档中的预定流程写成已经完成的事实。

## 资源生命周期与剩余边界

代码预检发现当前会话合同的物理 workspace_root 仍为 dev，而非任务工作树。
标准 release-completed-workspace 在源/目标相同时会拒绝；若正式释放仍遇到该情况，
保留已合并任务工作树和分支，不手改合同，不执行强制删除，不称清理完成。
此前已合并的 release-evidence-correction 任务资源不属于本轮清理范围。

CLI 0.155.1 与仓库审计版本 0.154.0 的差异仍是独立发布门禁；本地集成不等于可以正式安装。
未进行 Windows/Linux 实机验收、生产 Hook 或生产调度验收，不宣称整体发布闭环。

## 技能影响与沉淀候选

dispatch-task 保持当前宿主配置；intent-guardian 将修复、集成与安装的权限范围分开；
kb-search 命中《Git 多工作树的内容证据与检出后物化》，因此分别核验 index、提交树及
检出内容，而不是只看 git status。无需为相同内容重复执行昂贵原生测试。

候选：普通归档路径若落入受保护控制工件目录，即使已批准 local_write 仍会被拒绝。
本次拒绝事实 verified；策略是否应调整不属于本轮修复。
路由正例：私有测试日志落入控制目录；路由反例：业务日志在明确批准的非控制目录。
执行合格例：拒绝后保留原件、明确修订目标并逐字节验证；执行失败例：直接绕过路径保护
或移除原日志。正式入库前去除机器、会话及仓库标识。
