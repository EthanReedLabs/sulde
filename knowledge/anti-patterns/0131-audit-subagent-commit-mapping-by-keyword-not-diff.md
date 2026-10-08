---
doc_id: "ap-0131"
container: anti-patterns
platform: none
summary: "0131 audit subagent 把 commit 归为某需求修复时凭 commit message 关键词匹配…"
---

# 0131 audit subagent 把 commit 归为某需求修复时凭 commit message 关键词匹配,未 verify diff

- **平台**:协调端
- **复发次数**:0

## ❌ 错误

协调端 audit subagent 跑 cross-verify(跟踪表 X 项 vs git log)时,**凭 commit message 关键词匹配**(如"credits"匹配某筛选需求)就标"X 项已修",不 verify diff 实际改了什么文件 / 什么字段:

```
audit subagent: "需求 X → commit abcd 修"
实证:git show abcd --stat → 7 文件,主要是积分同步;
      git show abcd -- <需求 X 相关 file> → 仅加 5s 重拉 trigger,0 字段相关
→ ❌ 双重误判:① 归错 commit ② 真实状态错(需求 X 其实早已实现,与该 commit 无关)
```

## 为什么错

- 凭关键词撞名归错 commit + 真实状态判断错(标"已修"但实际早已实现 OR 根本未实现)。
- 若按 audit 报告 sync 跟踪表 → 跟踪表错记 → 后续不再 audit → 真实状态长期不明。

## ✅ 正确

audit subagent prompt 必含"verify diff 实际内容"强制段:

```markdown
凡声称 "commit X 修了需求 Y" 必有 3 步实证:
1. git show X --stat(列改动文件清单)
2. git show X -- <需求 Y 相关 file path>(verify diff 真改 Y 相关字段)
3. 对照需求 Y 描述,diff 不含 Y 相关字段 → ❌ 拒判 / 改标 "误判候选,人工 verify"

判定线:
- ✅ diff 含需求 Y 直接相关改动(reducer 字段 / UI 组件 / 业务逻辑)→ 可标 "X 修了 Y"
- ❌ 仅同 Feature / 同 namespace 旁支改动 → 必标 "X 与 Y 无关 / 误判候选"
- ❌ commit message 含关键词但 diff 不动相关 file → 必标 "误判候选"
```

协调端凭 audit 报告 sync 跟踪表前必 verify diff;audit 误判命中 → task md 标 "audit-first"(让 Dev Stage 1 自审 verify)。

## lint 状态

❓ 中等(audit 报告 markdown 写作期 lint)— 检查报告内 "commit X 修了 Y" 是否含 diff quote / 文件清单;缺 → 警告需 verify。

## subcase:协调端把已钦定的设计真值当"待 PM 决策"外推

协调端 audit 发现"双端实施都偏离设计真值"(例:某卡片双端都用渐变,设计真值明示纯色)→ 误判为"设计真值可能错 / 设计师未严格遵循",借口"避免双端改错方向"升级成 PM 决策外推给客户。实际**违反数据源优先级铁律**(设计真值 > PRD > 实施 > 历史代码)+ 逃避协调端职责。

防复发:
1. 数据源优先级铁律 — 设计真值已钦定的事**不许让客户/PM 二次决策推翻**。
2. Dev escalation "向客户确认 X" 时,协调端必先 verify 该 X 在设计真值中是否已明示;已明示 → 按真值派 fix task md,不进 PM 文档;未明示 OR 与 PRD 冲突 → 才进 PM 文档。
3. 协调端职责:数据源齐全的项**直接派 Dev**,不齐全的才走 escalation。
4. 起 PM 文档时自问"这项数据源齐吗?齐 → 不该问 PM"。

## 关联

- adapter wrap ≠ 真链路(同源:凭单一证据 / 凭关键词匹配反推)
- 协调端跨端镜像 L10n key 多用未 grep(同源:baseline 凭印象)
- 用户反馈不是真值(反向:设计真值是真值,不该让客户推翻)
