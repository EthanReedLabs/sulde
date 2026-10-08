---
doc_id: "work-model/skills/dev/postmortem"
container: work-model
platform: cross
summary: "Dev 通过三问漏斗把已验证修复转成反模式、lint 或人工 review 的协调端 handoff。"
---

# Bug 修复事后沉淀

这是沉淀体系 Dev 侧入口。仅在修复已完成且有根因证据时运行；未修好、纯功能开发或仅有猜测时不运行。

## 三问漏斗

### Q1：以前踩过吗？

从 diff、症状与根因提取通用关键词，查询反模式登记与知识库；命中后补充复发证据，不创建重复条目。必须读取命中的原文全文。

### Q2：会再踩吗？

判断同类模式是否可能在其他模块、其他 Dev 或另一平台复发。不会复发的一次性事故只留修复说明；会复发才进入 Q3。

### Q3：能否自动检查？

能稳定用 AST、编译器、lint 或低误报 grep 识别时，提供规则草稿和最小正/反样例；否则把检查项加入 code-review checklist，禁止强造 grep。

若需要判断跨平台适用性，作为 Q3 的末项回答：Android 与 iOS 是否共享同一工程模式？共享则在 handoff 中列对端任务要点；平台机制不同则明确 `Android-only` 或 `iOS-only` 及理由。

## 产出（最多三项）

1. 反模式登记草稿：错误、为什么错、正确做法、复发次数、平台与 lint 三态。
2. lint 草稿：仅在 Q3 可自动检查时生成，必须通过语法检查并对当前代码真跑一次。
3. 对端任务要点：仅在跨平台适用时写入 handoff，由协调端分派。

```markdown
# 反模式登记草稿：{通用标题}
- 平台：Android / iOS / 跨端
- 复发次数：
## ❌ 错误
{不含业务名与内部路径的最小片段}
## 为什么错
{平台机制与根因}
## ✅ 正确
{通用修复模式}
## lint 状态
- Android: ✅ / ⏳ / ❌（理由）
- iOS: ✅ / ⏳ / ❌（理由）
- 人工 review：
```

## 平台 lint 差异

Android:
- Kotlin/Java 优先使用 detekt、ktlint、自定义编译检查或结构化扫描。
- 文件范围应排除 build、生成物和 worktree 镜像；规则需覆盖 Kotlin/Java 的真实语法边界。

iOS:
- Swift/Objective-C 优先使用 SwiftLint、自定义编译检查或结构化扫描。
- 文件范围应排除 `.build`、派生物和 worktree 镜像；Shell lint 至少通过 `bash -n`。

## 单写者边界

Dev 不直接写共享反模式集合、协调端目录或对端任务区。所有跨边界内容写入本端 `.ai-workspace/handoff/{日期}-{slug}.md`，包含完整条目草稿、对端要点、本端 lint 三态和验证证据，由协调端统一判重、编号与落库。

## 有对有账自检

- 声明 ✅ 的 lint 文件必须存在、语法通过且已实际运行。
- 声明存在的报告、截图或任务只能引用真实产物；尚未创建则标 ⏳，不能写 ✅。
- handoff 中的路径必须位于本端允许区域，不得跨写协调端或另一端仓库。
- 展示修改文件与验证结果，不自动 commit。
