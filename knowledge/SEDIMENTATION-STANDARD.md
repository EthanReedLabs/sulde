# 沉淀贡献标准(SEDIMENTATION-STANDARD)

> **项目无关**。任一来源项目(Freebeat / iquokka / 未来项目…)把内部沉淀通用化后贡献进本知识库,都走本标准。
> 前身是 `ABSTRACTION-GUIDE.md`(Freebeat 首个来源项目的抽象指南)——那份保留为**首个来源项目案例**,本标准是其项目无关升级版。

---

## 0. 一句话

**内部详尽(Layer1,各项目自留)→ 按脱敏铁律通用化 → 贡献到本库 5 类(Layer2)。** 编号跨项目全局单调递增,平台用受控词,新增前先 dedup。

从 sedimentation v2 起，Layer2 不再只保存“错误—原因—正确”的结论，还必须保存：
**问题语境、证据状态、适用边界、路由正反例、执行正反例、实际消费者**。统一 schema
见 `templates/knowledge/schema.json`，五容器模板见同目录。

---

## 1. 两层模型(跨项目通用)

| 层 | 位置 | 内容 | 外发 |
|---|---|---|---|
| **Layer1(内部)** | 各来源项目 `<repo>/docs-hub/`(反模式 ADR / harmony-kb / audit / handoff / bugbook)| 详尽,含 commit / 类名 / 页 ID / 人名 / handoff | ❌ 不外发 |
| **Layer2(本库)** | `sulde-cc-pro/knowledge/` | 脱敏、项目无关,跨项目复用 | ✅ 公开 |

**唯一通道**:Layer1 → 通用化 → Layer2。禁止 Layer1 原文直拷进 Layer2。

### 1.1 Layer1 原始问题卡

新素材先按 `templates/knowledge/problem-card.md` 记录。问题卡必须回答“在什么任务与约束下
发生、用户/系统看到什么、期望与实际差什么、根因由什么证据支持”，并收集四类样本。
Layer1 可以保留内部路径、提交与用户原话；Layer2 只能留下脱敏的问题原型和通用证据。

`evidence_status` 只有两值：

- `verified`：有可回读的一手证据支持根因和正确做法；
- `inconclusive`：已确认信息不足，并明确写出缺失证据及安全下一步。未经验证的猜测不能
  借此进入 KB。

---

## 2. 本库 5 类容器(贡献落点)

| 类 | 目录 | 收什么 | 脱敏度 | 编号 |
|---|---|---|---|---|
| **反模式** | `anti-patterns/` | 单点反模式(❌错误/为什么/✅正确/lint)| 留方法论词,删项目特有 | 全局续号 |
| **平台知识库** | `platform-kb/{platform}/` | 平台事实速查(rules + workaround lookup)| 留平台 API,删项目页名/版本来源 | 无(按平台分类)|
| **技术文档** | `tech-docs/` | 通用原则 / 设计模式 / 转译规则 | 留方法论词 | 无 |
| **案例研究** | `tech-docs/案例研究/{域}/` | 深复盘(⭐⭐⭐⭐+ 或强可移植)| **全脱敏**(连方法论词也不用)| 无 |
| **工作模型** | `work-model/` + `skills/` | 工作法规则 / 协调端·Dev 技能 | 留方法论词 | 无 |

> `platform-kb/` 与「案例域」是随平台扩展的**加法维度**:新平台来源项目 → 新增 `platform-kb/{platform}/` + 案例研究新域,不动既有编号/域。

---

## 3. 脱敏铁律(所有类通用)

### 删(项目特有,必删/改写)
1. **项目名 / 包名**:`Freebeat` / `iquokka` / `com.xxx.app` → "本项目 / 某应用"
2. **commit hash / 分支名 / MR 号**:`8c308f0e` / `dev/xxx/yyy` → 删(留"某次修复")
3. **具体类 / 文件路径 / 行号**:`MvAgentActivity.kt:177` → `<某 Activity>` 或删行号
4. **页 ID / PRD§ / 反模式§**:`03A1B` / `§6.5` → "某参数页 / 工程约束"
5. **业务功能名**:MV Agent / Onbeat / 每周来信 / credits → "某创作流 / 某列表页 / 某操作面板"
6. **人名 / 日期**:真实人名 / `2026-xx-xx` → 删或"开发团队"
7. **内部文件引用**:`xxx-result.md` handoff / xlsx / 截图路径 / memory 文件名 → 泛化

### 留(方法论通用词,不删)
协调端 / Dev / 甲方 / 设计稿(.pen 概念)/ pen-truth / task md / handoff / 敏感清单 / worktree / 完工三步 / scaffold / 三态视图 / MVI / TCA / SSE / 真机验证 / baseline / 反模式编号 / 平台名(Android / iOS / HarmonyOS)。

> **例外——案例研究更严**:技术案例**连方法论词也不用**(不写协调端 / task md / handoff),项目名 / 包名 / endpoint / CDN / commit / 人名 / § 全删,只留项目无关工程内核 + 通用平台机制。

---

## 4. 编号规则(反模式,跨项目全局)

- **全局 append-only 单调递增**:不分项目、不分平台共用一个序列。新批次接最后一号往后续(当前最后 = `0141` → 下一批从 `0142`)。历史空号(如 `0080` / `0100`)不回填。
- **同名同编号可溯源**:文件名 `NNNN-kebab-slug.md`,slug 取通用化后的英文关键词。
- **结构**:`# NNNN 标题` → `- **平台**:<受控词>` → `- **复发次数**:N` → `## ❌ 错误` → `## 为什么错` → `## ✅ 正确` → `## lint 状态`(+ 关联)。删"首次踩坑日期/来源 handoff"等纯项目元数据。
- **平台受控词**:`Android` · `iOS` · `HarmonyOS` · `跨端` · `协调端方法论`(对齐 ADR frontmatter platforms enum `android/ios/flutter/harmony/coordinator/any`)。
- 新增后**更新 [`anti-patterns/INDEX.md`](anti-patterns/INDEX.md)** 对应平台段。

## 4A. frontmatter 必带(检索契约)

新沉淀文件必须在文件顶部携带 `doc_id`、`container`、`platform`、`summary` frontmatter。
字段含义、受控词与目录映射统一遵循 [`docs/kb-retrieval-contract.md` §2](../docs/kb-retrieval-contract.md#2-文档-schema标准结构化的核心)。
`doc_id` 必须稳定且全局唯一；`summary` 必须是非空的一句话摘要。
`related` 可选；填写时，每个目标都必须是库内已存在的 `doc_id`。
提交前运行 `python3 scripts/kb/lint-frontmatter.py`，任何违规均须修复后再提交。

### 4B. sedimentation v2 结构契约

所有**新增**知识文档，以及被实质合并更新的旧文档，必须使用 v2：

```yaml
sedimentation_schema: 2
problem_type: <受控问题类型>
evidence_status: verified | inconclusive
```

正文必须覆盖九类语义：问题原型、根因与证据、适用边界、路由正例、路由反例、执行合格
例、执行失败例、正确做法、消费与防复发。只新增 `related` 反向链接不算实质合并，可暂不
迁移；存量文档按“被使用、被合并时迁移”，不做一次性空壳批量改写。

四类样本必须分别带判定原因和来源：`observed` 表示真实出现，`constructed` 表示为边界或
回归而构造。构造样本不得写成历史事实。预期值固定为：

| 样本 | 预期 | 用途 |
|---|---|---|
| 路由正例 | `apply` | 提高应召回场景的命中 |
| 路由反例 | `skip` | 防止相似表象导致误注入/规则过度适用 |
| 执行合格例 | `pass` | 定义实质验收下限 |
| 执行失败例 | `fail` | 捕捉“看似完成”的假阳性 |

结构门禁校验语义角色、受控值和样本内容，不要求固定列表条数或排版。模板是默认载体，
不是以形态冒充质量。运行 `python3 scripts/kb/lint-sedimentation.py` 验证。

独立改写回归不能复述文档内样本。运行
`python3 scripts/kb/sedimentation-search-eval.py --min-rate 1`：目标文档和预期语义必须进入
top-3，显式 `skip` 边界还必须位于 top-1；报告同时披露 exact top-1，旧格式知识造成的
排序债务不得用固定加分或降低阈值隐藏。

---

## 5. dedup-before-add(新增前必做)

新增任一反模式/文档前,**先 grep 本库同主题**,命中已有条目 → **补充**而非新建重复:
- 补 `**复发次数** +1`
- `**平台**` 追加新平台(如既有跨端条目补 `+ HarmonyOS`)
- 追加新平台的 workaround / ✅ 正确分支

典型 dedup 对(iquokka 批已知):worktree 类 ↔ `0070/0071` · 复用绕过 ↔ `0097/0138` · 单状态截图 ↔ `0141` · ultrathink/parallel ↔ `0065/0066`。

### 5.1 跨容器"重复"不是重复——体裁分工(2026-08-10 定稿)

**同一知识可在 `anti-patterns` 与 `案例研究`/`platform-kb` 各存一份,二者不合并、以 `related` 互链。**

| 体裁 | 服务对象 | 形态要求 |
|---|---|---|
| `anti-patterns` 条目 | **检索命中**(模型注入/grep/lint) | 精炼、可 grep、带 lint 规则与 review checklist;注入时占上下文小 |
| `案例研究` / `platform-kb` | **人类阅读 / 平台速查** | 完整根因推演、被拒方案论证、Q&A;或平台事实全景。叙事与全景不可压缩 |

合并会两头受损:案例研究被压缩则失去论证价值,反模式变臃肿则拖累检索与注入。

**判重判据顺序**:
1. **容器不同** → 优先交叉链接(`related` 互链),**不提合并**;
2. 容器相同 + 同根因 → 并入(§3A 流程),保留信息更全者,独有内容(尤其 lint 闸门、
   复发次数等治理元数据)必须并入保留稿;
3. 容器相同 + 同主题不同根因 → 系列新增 + 互链;
4. 平台/技术栈不同(如 Android XML ↔ SwiftUI 的同类问题) → **不合并**,
   合并会丢失一侧可执行细节。

自动判重官(`kb-dedup`)须遵守本节;其提案中凡跨容器对,应输出"交叉链接"而非"建议合并"。

---

## 6. 案例研究三道门(curate-to-kb)

案例研究**不直写**,走执行器起草 → 协调端质检三门:
- **C 验真**:对照 source 防杜撰(双端案例 grep 核对另一端)
- **A 质量**:对齐标杆深度,只许更高不许更低(标杆见案例域 README)
- **B 脱敏**:逐条过 §3 禁→改表 + 案例研究"更严"例外

达标 → promote 到 `tech-docs/案例研究/{域}/` + 更新域 README 案例数 + 留底镜像。详 `skills/coordinator/curate-to-kb/SKILL.md`。

---

## 7. 各来源项目留底约定

抽象结果**双留**:目标仓 `knowledge/` + 来源项目 `<repo>/docs-hub/_sulde-sync/`(镜像 anti-patterns / platform-kb / tech-docs / 案例研究 的本批产物)。留底便于溯源"这条通用反模式源自本项目哪次事故"。

---

## 8. 提交流程

1. 目标仓开 feature 分支(`feat/sediment-<source-project>-<topic>`)。
2. 按 5 类落地 + 更新 INDEX / 案例域 README / 平台 KB README。
3. 更新 `CHANGELOG.md`(不 bump version,除非维护者发版)。
4. 验证无残留内部痕迹(全库 grep 项目名 / 包名 / endpoint / commit / 人名 / §)。
5. 路由正反样本 + 执行正反样本进入实际消费者回归；没有消费者时明确写“仅供检索”。
6. commit → 维护者 review / 合并。

---

## 附:与 ABSTRACTION-GUIDE 的关系

`ABSTRACTION-GUIDE.md` = 首个来源项目(Freebeat)的抽象指南,措辞含 Freebeat 语境,保留作**历史案例**。本标准把其规则抽象为项目无关版,后续所有项目以本标准为准;两者冲突时以本标准为准。
