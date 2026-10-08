# r22 — 分层发布验收（非生产安装）

状态：revision 22 已执行完；L1 开发候选与 L2 冻结源码发布门限定复核通过。
详见 R22-RELEASE-VERIFICATION-REPORT.md；不是生产安装或版本发布批准。
基线：2108178d00824b5d56ce99311a94aedb5e1c66c5。
原 worktree / task/guardian-update-continuity；执行宿主 Codex；capability_tier: deep。
receipt: aa66e32265c43d9821917985777772f8e2111aa8efb3c2be3662303fe7860cea。

目标：在 r21 源码限定复核通过后完成开发候选 L1 和新源码 L2 发布全量，
不是完成 L3。90 活跃分钟，无付费模型调用；禁止关闭宿主或扩建 GUI/VM。
预期只改本目录任务文档与证据 runner，不改产品源码、测试断言、版本。

步骤连续执行：

1. 核对原分支和 clean 输入，确认 dev 仍被包含；生产只读记录不作为新验收。
2. 记录器显式绑定已复核源码，任务文档差异可声明，其他 tracked 差异拒绝。
3. 官方 Codex prepare/verify 与 Claude stage/strict manifest 检查，隔离候选
   使用唯一临时根；保留当前版本，明确其不允许覆盖同版本已安装内容。
4. 冻结提交后一次官方 full，保留源/依赖/夹具/日志/退出结果及 input drift。
   期间不修改 tracked 输入。正常入口与受影响测试已在 r21 通过，不重做修复。
5. 同一独立复核线程集中回读；唯一归档 Optimus，成功/失败均保留。

边界：只有证明的 L1/L2 子项可升级状态。真实 native maintenance、launchd、
宿主信任/新旧会话 live Hook 和逆向属于 L3。版本/cachebuster 与最终发布件
须后续精确绑定；本卡不授权安装、回退、合入、推送、生产账本修改。
发现产品阻断时保留首个失败事实，不改断言、不借旧 full 豁免、申请有界返修。
两次同类失败无新增证据改变诊断；不因单个阶段通过请求重复“继续”。

产物：本目录报告；`.codex-agent/layered-r22/<run>/`、正式 test-evidence 记录；
Optimus `Sulde/tasks/guardian-unified-plan-20261004/S3-C-repair/r22-*` 唯一归档。
回退：不碰生产；不覆盖旧证据；文档可反向提交。未完成则精确 checkpoint。

知识依据：已全文回读 schema-fixture-migration-and-real-execution，采用“实际
入口执行与夹具替代范围分开、环境失败不当产品通过”。final-backup-before-
migration-cutover 仅为未来 L3 恢复事实提示，本轮没有生产切流/备份动作。
