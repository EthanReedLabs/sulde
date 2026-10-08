---
doc_id: "work-model/self-fix-boundary"
container: work-model
platform: none
summary: "子端 Dev 自发修小 bug 时的硬约束,作为唯一真值。"
related: [ap-0218]
---

# 自发修复边界(三端共享)

> 子端 Dev 自发修小 bug 时的硬约束,作为唯一真值。

---

## 核心机制:能力分布

| 能力 | 下沉到 Dev? | Why |
|---|---|---|
| **规则 cognition** — pen-truth 优先 / 敏感清单 / commit 拟人化 / mini-checklist | ✅ 必须下沉 | Dev 自发修 bug 时也按规则来 |
| **任务调度** — 谁做什么 / 多任务并行 / 跨端协调 | ❌ 留协调端 | 单一审计入口,防止 Dev 互相覆盖 |
| **数据源生成** — Pencil MCP 提取 pen-truth / page-relation 维护 | ❌ 留协调端 | 跨端唯一真相源 |
| **反模式登记** — §x.y / lint 规则草稿 | ⚠️ Dev 端通过 handoff 发起,协调端写入 | 知识共享区单一写入 |

---

## 敏感清单(自发禁改 — 改这些必须先 handoff 协调端)

| 类别 | iOS 具体内容 | Android 具体内容 |
|---|---|---|
| **wizard 结构** | `stageNames` 数组项数 / `Step N of M` 文本(M 改动)/ `stageContent` switch case 数 / wizard step 路由 | `stageNames` 数组项数变化 / `Step N of M` 文本(M 改动)/ Fragment switch / 路由 / `setupFooter(stepIndex=N)` 的 stage 总数 |
| **数据源切换** | Mock URL 大批替换 / API endpoint / Spec 接口契约(各 Client) | Mock URL 大批替换 / API endpoint / Spec 接口契约(各 Service) |
| **scaffold 层** | `AdaptiveScaffold` / `AppRouter` / `AppTopBar` / `AppColors` / `AppTypography` / `AdaptiveStateView` / pen-truth 关键属性(fill/stroke/cr/字号 跨页统一) | `AdaptiveBaseActivity` / `AdaptiveBaseFragment` / `AppRouter` / `AppTopBar` / `AppColors` / `AppTypography` / `AdaptiveStateView` / pen-truth 关键属性(fill/stroke/cr/字号 跨页统一) |
| **page-relation 类** | type 字段(page/modal/state)/ states 分支 / parent / next | type 字段(page/modal/state)/ states 分支 / parent / next |
| **scope 扩散** | 单 commit 涉及 ≥3 文件 OR 跨 ≥2 Feature module | 单 commit 涉及 ≥3 文件 OR 跨 ≥2 Feature module |

命中清单 = **STOP**,**先 handoff,不自发改**。

---

## 自发修复 mini-checklist(commit 前 5 问)

| # | 问题 | 命中处理 |
|---|---|---|
| 1 | 改的字段在敏感清单里吗? | 是 → STOP,handoff 给协调端 |
| 2 | 涉及视觉/文案/stage 数 → Read pen-truth.md + .png 了吗? | 否 → 先读再改 |
| 3 | 改的范围是否只在原始 bug 内?(diff 文件数 / 行数 / 字段) | 否 → 拆 commit,无关改动单独走 |
| 4 | commit message 拟人化短句?(无 Phase / 批次 / P0 / emoji) | 否 → 重写 |
| 5 | `#once`(一次性)或 `§x.y`(沉淀型)标注? | 否 → 补一个 |

任一问 ❌ → 不要 commit,先纠正。

---

## handoff 模板(命中敏感清单时)

```markdown
# handoff: 请协调端派 task — {bug 描述}
- 触发场景:{用户在 X 终端报 Y bug}
- 我看到的现象:{具体现象}
- 命中敏感清单:wizard_structure / data_source / scaffold / page-relation / scope
- 不自发修原因:命中敏感字段(具体哪个)
- 建议改动范围:{我看到的范围,供协调端参考,不自动派}
```

handoff 路径:`.ai-workspace/handoff/{YYYY-MM-DD}-{slug}.md`,提示用户「请把 handoff 文件交给协调端处理」。

---

## 反例 vs 正例

| 场景 | ❌ 错误 | ✅ 正确 |
|---|---|---|
| 用户报"返回按钮重建界面" | 修返回 bug 顺手"补一个新阶段"(改 stageNames / footer "of N")| 返回 bug 单独 commit `fix: 返回不重建 #once`;觉得"应该补新阶段"→ STOP,handoff 协调端验证 pen-truth 真值后再决定 |
| 用户报"卡片图加载失败" | 直接把 Mock URL 全部换成新 domain | 命中"数据源切换"敏感清单 → handoff 协调端写 task md(可能涉及 iOS / Android 同步换) |
| 用户报"scaffold 缺一项" | 自己在 CoreUI / core-ui 加新 scaffold 组件 | 命中"scaffold 层"敏感清单 → handoff,框架脚手架规范由协调端管 |

---

## Why 这套机制

- "再加严 task md"(协调端约束)只在 task md 路径生效,Dev 自发 commit 时全部失效
- 不能一刀切"禁所有自发 commit" — 用户报小问题继续要让 Dev 直接修,提速
- 真正问题不是"自发修复",是"修 X 小 bug 时扩散到 Y 大流程改动"
- 解 = Dev 端拥有规则 cognition + 敏感清单 STOP + mini-checklist 自检
- 80% 小 bug Dev 自发,20% 敏感改动 handoff 协调端

---

## 与多联防护的关系

- task md 路径协调端约束(协调端写 task md 时遵守)
- 自发修复路径 Dev 端约束(本节,Dev 自发 commit 时遵守)
- 两条路径合起来 = 完整闭环

---

## 关联

- 反模式集合(自发修复扩散完整论述)
- shared-rules `data-sources.md`(Dev 自发改时也要按 pen-truth)
- pre-commit hook 防护(敏感字段 grep 软警告)
