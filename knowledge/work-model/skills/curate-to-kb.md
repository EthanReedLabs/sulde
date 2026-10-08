---
doc_id: "work-model/skills/curate-to-kb"
container: work-model
platform: none
summary: "关联:概要版见 ../postmortem-generalization.md,本文是完整操作流"
sedimentation_schema: 2
problem_type: workflow
evidence_status: verified
name: curate-to-kb
description: Layer1 内部知识库上浮到 Layer2 案例研究知识库的 curation 流程；触发词：上浮知识库 / 精选 curate / Layer1 转 Layer2 / 沉淀欠债告警后精选 / pre-release 知识库 / 把 bugbook 转案例研究 / curate-to-kb
user-invocable: true
---

> 关联:概要版见 ../postmortem-generalization.md,本文是完整操作流

# Layer1 → Layer2 知识库上浮（curation）

## 问题原型

来源项目积累了包含内部路径、提交和业务细节的深度复盘，需要把其中跨项目可迁移的工程
内核上浮为公开 Layer2。直接复制会泄露内部痕迹；过度压缩又会丢失问题语境、证据、边界
和正负样本，使案例既不可验证也无法被 Agent 正确消费。

## 根因与证据

Layer1 与 Layer2 的服务对象和脱敏要求不同：前者保存一手工程事实，后者服务跨项目复用。
既有案例质检的 C/A/B 三门分别验证事实、质量和脱敏；新增结构契约进一步验证适用边界与
四类样本。缺任一门都会造成杜撰、泄漏、浅层总结或错误召回。

## 适用边界

适用于难度较高或强可迁移、已有一手来源并能完成脱敏的工程复盘。不适用于纯字段修改、
半验证猜测、项目进度和仍未合入的临时实现。无法确认根因或样本来源时保留 Layer1 并标
`inconclusive`，不得为了完成上浮而补写事实。

## 判定样本

### 路由正例

- **输入**：内部 bugbook 有完整复现、根因和复测，需要形成跨项目案例研究
- **预期**：apply
- **原因**：存在可验真的高价值 Layer1 来源并满足通用化条件
- **来源**：constructed

### 路由反例

- **输入**：某功能分支尚未合入，只记录当前完成进度和下一步待办
- **预期**：skip
- **原因**：这是项目私有状态且尚非最终工程真值
- **来源**：constructed

### 执行合格例

- **做法或输出**：案例通过验真、质量、脱敏和结构四门，并带 apply/skip/pass/fail 样本
- **预期**：pass
- **原因**：事实可追溯、边界明确且能进入实际检索和回归消费
- **来源**：constructed

### 执行失败例

- **做法或输出**：把内部复盘直接复制后只删除项目名，没有验证根因或补适用边界
- **预期**：fail
- **原因**：仍可能泄露内部关系，同时无法防止同症不同因的误应用
- **来源**：observed

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
2. 执行器（codex / subagent）读 source + 标杆 + 本脱敏表 → 起草到 `<docs-hub>/.ai-workspace/kb-backfill/drafts/`（禁直写 Layer2）
3. 协调端 gate 三道门：**C 验真**（对照 source 防杜撰，双端案例 grep 核对另一端）/ **A 质量**（对齐标杆深度，只许更高不许更低）/ **B 脱敏**（逐条过下面禁→改表）
4. 达标 → promote 到 `knowledge/tech-docs/案例研究/{域}/{slug}.md` + 更新 README 案例数 + 同步留底镜像
5. 不达标 → 退回重出

## 正确做法

严格执行下面的选源、C/A/B 质检、统一模板和 measured/expected 区分；结构门作为第四门，
确保问题语境、边界、四类样本及消费入口真实存在。协调端只在全部门禁通过后 promote。

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

标杆：`knowledge/tech-docs/案例研究/01-Android媒体与性能工程/视频列表四类典型缺陷与离屏渲染架构.md`

## measured / expected 诚实区分

实施中 / 未复测的优化：实测数值写"已观测"，未验证收益写"预期 / 方向"，不假报上线收益。

## 判定线（Gate3）

- Layer2 案例若残留任一内部痕迹（全库 grep 项目名 / 包名 / endpoint / commit / 人名 / § 命中）= 不合格，打回
- Layer1 原文直拷进 Layer2 未脱敏 = 严重违规

## 消费与防复发

本流程由 `curate-to-kb` Skill 消费，`lint-frontmatter.py`、`lint-sedimentation.py`、
脱敏扫描和案例 review 共同验收。路由正反例进入检索评测，执行正反例进入模板与门禁回归；
涉及叙事深度、事实等价和脱敏语义的部分仍由协调端人工拍板。
