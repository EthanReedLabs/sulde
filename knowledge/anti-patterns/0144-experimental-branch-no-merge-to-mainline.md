---
doc_id: "ap-0144"
container: anti-patterns
platform: cross
summary: "spike/实验分支禁 merge 回主干(简化版入口/系统文件回灌主链路)"
---

# 0144 — spike/实验分支禁 merge 回主干(简化版入口/系统文件回灌主链路)

- **平台**:跨端
- **复发次数**:1
- **lint 状态**:pre-merge hook 可拦(见 ## lint 状态)

## 现象

一条 spike / throwaway / 实验用 branch(`spike/<slug>`)为隔离测试,携带**简化版的系统级文件**:入口 Ability/Activity/main 被换成精简版(几十行替生产上百行,跳过正式 bootstrap / 三方 SDK 初始化)、路由表加了 spike 专用 route、loadContent 指向 spike 页。

这条 branch 被 ff-merge / merge 进主干(mainline)后 —— **主干应用启动加载的是 spike 页而非生产主页,主链路入口失效、应用起不来**。系统级文件被 spike-only 版本覆盖了主干。

诱因:cleanup / 收尾时误批 merge;task 契约未列 "audit branch 内容是否改了系统级 file" 的 checklist;人工决策 merge 时无 audit gate。

## 为什么

- spike branch 的入口/系统文件简化模式**只对 spike branch 自身有效**,主干不该受影响 —— 但一旦 merge,git history 把简化版直接灌回主干。
- spike 的价值是"验证一个想法",其**产出应通过文档/知识库沉淀**(结论、踩坑、决策),而**不是靠 git 合并把实验代码搬进主干**。实验分支天然携带简化/删减,merge = 把这些 regression 带进主链路。
- 系统级 file(入口 Ability、路由表)与业务 file 不同:改一处就动全局启动链路,静态 diff 若无人审很容易漏。

## ✅ 正确

- **命名即约束**:`spike/*`(或等价实验前缀)branch **禁 merge 回主干**。spike 真值走文档 / 知识库 / ADR 沉淀,绝不通过 git history 入主干。
- **唯一例外**:纯新增 spike 页路由**且不触碰生产入口文件**(新加一个 demo/test entry,不替换入口 Ability、不改 loadContent 指向)—— 这类可作为永久 demo 保留。
- **实操判定门**:diff 入口文件行数变化超阈值(如 >50 行)**或** loadContent 指向 spike 页 → block merge。
- 收尾 / cleanup 类 task 契约必含 checklist:"audit 本 branch 是否改了入口/路由等系统级 file,是否被 spike-only 版本隔离修改";人工决策 merge 前先过此 audit gate。

## lint 状态

- ✅ 可 hook:`pre-merge-commit` 钩子跑脚本,检测被 merge 的 `spike/*` branch 是否含入口/系统文件大改(行数阈值 + loadContent 指向 spike),命中则拒绝 merge。
- 收尾 task 起草 checklist 兜底人工审。
- 关联:反模式 [[0070]](直接 commit 主干/develop —— 本条是其"实验分支携简化系统文件"的特化)、[[0071]](worktree 创建位置纪律)。三者同属 git 隔离纪律簇但场景不同:0070 = 直提主干,0071 = worktree 落点,本条 = 实验分支禁回灌主干。
