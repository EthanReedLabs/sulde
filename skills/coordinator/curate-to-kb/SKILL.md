---
name: curate-to-kb
description: Layer1 内部知识库上浮到 Layer2 案例研究知识库的 curation 流程；触发词：上浮知识库 / 精选 curate / Layer1 转 Layer2 / 沉淀欠债告警后精选 / pre-release 知识库 / 把 bugbook 转案例研究 / curate-to-kb
---

# Layer1 → Layer2 知识库上浮（curation）

## 何时 invoke

- 每周 / pre-release / baseline §7 沉淀欠债告警偏高时
- 把内部 Layer1（`<docs-hub>/_bugbook` + 反模式 ADR）里达标的工程复盘，脱敏精选成 Layer2 案例研究

## 两层定位（必写清楚）

- Layer1 = `<docs-hub>/_bugbook` + 反模式 ADR：内部、详尽、含 commit / 类名 / 人名 / handoff，grep 复用，不外发
- Layer2 = `knowledge/tech-docs/案例研究/`：脱敏、项目无关、案例研究，跨项目复用 / 技术参考 / 人才培养
- 上浮是 Layer1→Layer2 唯一通道；禁止把 Layer1 原文直接拷进 Layer2

## 选源标准

- 难度 ≥ ⭐⭐⭐⭐ 或 强可移植（通用平台机制 / 跨项目适用）
- 跳过：纯字段/翻译/琐碎修复、半验证（用户侧表现未确认）、纯内部流程复盘（除非能 reframe 成通用方法论）
- 不重复 Layer2 已有案例

## 单篇流水线（执行器 + 协调端质检门）

1. 写 brief：source 路径 + 目标域(01~05) + slug
2. 执行器读 source + 下述案例模板和证据要求 + 本脱敏表 → 起草到 `<docs-hub>/.ai-workspace/kb-backfill/drafts/`（禁直写 Layer2）
3. 协调端 gate 三道门：**C 验真**（对照 source 防杜撰，双端案例 grep 核对另一端）/ **A 质量**（问题、根因、适用边界与四类样本有证据支撑）/ **B 脱敏**（逐条过下面禁→改表）
4. 达标 → promote 到 `knowledge/tech-docs/案例研究/{域}/{slug}.md` + 更新 README 案例数 + 同步留底镜像
5. 不达标 → 退回重出

## 脱敏铁律（B 门，禁→改）

| 禁（内部痕迹） | 改为 |
|---|---|
| 项目名 / 包名 / 真实 endpoint / CDN 域名 | 删或"某应用 / 某接口 / 远端 CDN" |
| commit hash / 分支名 / promise token | 删 |
| 真实人名 / 内部角色（工程叙述里） | "开发团队"或去主语 |
| 具体文件路径 / 内部类名 | 泛化（generic 类名 / 模块名） |
| 内部页号代号 / PRD § / 反模式 § | 删编号，写"某页 / 工程约束" |
| 纯内部流程复盘（凭印象 / audit 流程 / 终端纪律） | 整段删除（除非能 reframe 成通用方法论） |

## 案例统一模板

使用 `templates/knowledge/case-studies.md`。除场景/架构、现象、根因、方案和可迁移原则外，
必须补问题原型、适用边界、路由正反例、执行正反例和消费入口；样本逐项标
`observed|constructed`。模板固定语义，不限制图、表、段落或列表形态。

模板和 schema 随代码分发，不依赖正式知识库中的特定案例。若用户提供可访问且适用的参考案例，
可额外对照；没有参考案例时按模板和证据验收，不阻塞起草，也不宣称已对照不存在的标杆。

## measured / expected 诚实区分

实施中 / 未复测的优化：实测数值写"已观测"，未验证收益写"预期 / 方向"，不假报上线收益。

## 判定线（Gate3）

- Layer2 案例若残留任一内部痕迹（全库 grep 项目名 / 包名 / endpoint / commit / 人名 / § 命中）= 不合格，打回
- Layer1 原文直拷进 Layer2 未脱敏 = 严重违规
