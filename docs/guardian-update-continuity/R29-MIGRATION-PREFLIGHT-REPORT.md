# r29 — 已退休记忆归档的维护安装预检

2026-10-08；基线 `42c6f6d2e964f6d81a88a7eb4891988eaa956517`。
原任务分支 `task/guardian-update-continuity`。状态：源码修复与定向验证完成；
独立复核和证据归档通过，可有界合入 dev；生产安装未执行。

## 事实与范围

r28 原生安装批准后，worker 在安装事务建立前报
`maintenance cannot silently include home or memory migration` 并退出 1。
旧生产代际保留，没有 active install journal；不是等待批准或超时。
r28 candidate 已 `promotion_failed / promotion_consumed=true`，不得重置或复用。

旧 Claude 目录中的 memory.db 是 0444 的退休归档，不是待迁移源。
官方只读 plan 实测 `ready=true / missing_entries=0 / reconcile_required=false`。
原维护检查却把“存在另一份数据库”直接当成“需要迁移”，与普通安装的
reconciliation 判定不一致；prepare 阶段又未提前检查，故关闭宿主后才发现。

r29 仅授权原分支的预检修复、隔离测试、报告，以及通过复核后的提交和 dev
合入。没有授予记忆迁移、生产安装、关闭宿主、版本刷新、main 修改或推送。
不通过删除归档、改权限、改账本或跳过保护消除错误。

## 修复

- 共享只读预检：home 迁移继续拒绝；memory 仅在严格布尔
  `ready is True and reconcile_required is False` 时通过。
- 缺记录、可写源、损坏/不可读、未知计划仍拒绝。
- prepare_draft 在工件验证/草案写入之前执行同一预检；正式 installer 仍复检。
- maintenance 分支不调用 memory reconciliation writer；普通安装保留迁移能力。
- 独立复核另发现候选并发缺口：缓存的 migration_source 与 helper 最新读取
  可能不同。已增加对捕获非空来源的显式拒绝，避免进入 home writer。

## 验证记录（不跨层宣称）

所有测试使用 `python -B`。真实安装事务代码运行于临时根；宿主、调度与
候选证据为既有夹具，不是真人生产审批或实际生产切换。

- 相同正常/拒绝配对：基线 1 FAIL + 1 PASS（45.109s），候选 2 PASS
  （55.185s）；正常例失败原因就是上述旧归档误判。
- 快速预检 7 项通过（0.217s）；候选对生产数据库的只读预检通过（3.069s），
  未执行写入或安装。
- 首轮受影响批次因新普通安装对照误用了 legacy Hook 维护夹具而停止；
  `migration_required` 属于夹具设置错误，不是产品回归。原日志保留，退出 -2。
  修正为普通初次安装后，该对照独立通过（36.019s）。
- 六模块批次：104 项通过，824.159s，exit 0，输入摘要前后一致；对应
  `affected-1791428344028939000/`，属于增加最终两行 guard **之前**的证据。
- 候选并发缺口：同一序列反例修复前失败（22.646s），明确触达 home writer
  sentinel；不是旧基线已证缺陷。补上两行 guard 后，最终三个受影响模块
  30 项全部通过（159.017s，exit 0），含正常、拒绝、prepare 和实际事务入口。
  前后批次有重叠，不相加称为 134 项独立验收；未重新跑全仓测试。
- 最终 installer SHA256：
  `539042869c7247f8aa9347c0c26d1b960a265fef5dd6b233040e66790df192ef`；
  final-30.log SHA256：
  `aff54aa0100a7b93bc3f70ce469a8733650f97d8ba47f584a85b4e6fa65f7c54`。
  日志来自原工具返回分块的连接，不是重跑；初始输出逐字复制来源已在
  final-30-result.json 声明。序列故障测试仅替换文件系统来源探测结果和 writer
  sentinel，不能冒称实际生产并发演练。

独立复核（architecture_analysis）已回读最终源码、反例和日志摘要：无剩余
源码/测试阻断，同意 r29 有界提交并合 dev；不外推发布全量或 L3。
复核提出的唯一阻断即上述缓存来源竞态，已经修复并经前后对照确认。

本地原始证据位于 `/private/tmp/sulde-s3c-r24.mqyXRi/r29/`。最终归档：
Optimus `Sulde/tasks/guardian-unified-plan-20261004/S3-C-repair/r29-preflight-20261008T031831.701075Z/`，
20 文件逐项哈希回读一致。自排除清单 SHA256：
`be7de3762a8bff54228b323a228a5f214d0b5a0ee094b6ecd6da71e7203ac48f`。
保留失败与修正、输入摘要、退出码；归档报告早于本段归档地址补充，源码一致。

## 安装剩余事项

源码修复通过不等于安装完成。后续仍需冻结最终源码、按影响完成发布门、
生成新的候选和一次性 receipt，提前做维护只读预检，再绑定当时仍存活的
宿主身份申请正式维护。不能复用 r28 的进程清单、批准或已消费候选。
Codex 正式事务及真实 Hook/调度验收、Claude 独立官方安装仍未完成。
历史 L2 全量仅支持未变输入，不能改称本次 installer 新源码的全量结果。
