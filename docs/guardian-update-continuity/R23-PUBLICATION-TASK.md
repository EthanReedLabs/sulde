# r23 — 唯一发布件准备，非生产安装

2026-10-07，原分支 task/guardian-update-continuity；起点 8465482。
当前会话经原生 workspace-handoff 绑定任务物理 worktree；不继承旧权限。
r23 原生方案回执 e8621b84255ce0cc1e750b1f9c52a382abf43aa4290bd4328d3135781d1cc6f6。

## 冻结范围与连续执行

- Codex 官方密封 helper 更新版本；独立内容 verifier 完成后才更新 Claude。
- Claude manifest 仅 version 0.8.10 → 0.8.11。
- 任务 runner 增加 r23 唯一输出路径及显式版本差异检查；没有产品逻辑修复。
- 干净提交后官方 prepare/verify、Claude stage/strict validate、身份回读、
  唯一证据归档、集中独立复核连续执行，60 活跃分钟、零付费模型。
- 不合并、推送、promote、生产安装、杀宿主、清理真实代际或修改生产配置。

## 复用与验收

b3203536365e1ddaa69c5fc020a747d81b65a315 的全量结果为 2961 passed、29 skipped。
先证明产品代码、测试、依赖无变化，两个 manifest 除 version 外 JSON 完全相同；
任务目录的 runner 是可执行输入，按本轮真实运行验收，不能称作纯 Markdown。
不重跑未变化全量；重跑受版本影响的正式构建、候选实际入口和工件身份。
最终身份必须记录 source commit/tree 和 artifact digest，不能重标旧证据 HEAD。

Optimus 路径沿用 S3-C-repair/，新增唯一 r23 目录，不覆盖旧证据。
L3 仍需精确维护计划、新旧代际、cohort、独立恢复入口及原生人审；
本轮通过只能表示发布候选准备完成，不是 production operational_ready。

## 过程异常（保留）

第一次 helper 调用误用了 env 前缀。官方 helper 实际成功，但旧 Guardian 将其
记为 unknown/non_material_observation，没有消费 grant。事件
051e5e0747bbc3cda1e7128c 的真实 Pre/Post 保留，不能补称 system_verified。
按已批准恢复方法仅还原 version，git diff 确认原状，再使用已注册的精确
PYTHONDONTWRITEBYTECODE=1 + python -B 形状。正式调用事件
1a4ddde36e5540e5c5f8029d 消费 grant e01d3f… 一次，独立 verifier 将
att-b0f9ec8ff05a1fd0e5c8ecdf 结算为 system verification；pending/open/gap 均空。
本轮不修改分类器，也不掩盖首次调用的观测缺口。
