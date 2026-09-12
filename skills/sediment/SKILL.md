---
name: sediment
description: 引导式知识沉淀。把踩坑/BUG修复/性能优化经验沉淀进 knowledge/ 五类容器,先判重(并入更新 vs 系列新增 vs 全新),再脱敏成文,收尾自动跑 lint/INDEX/索引。修完值得记录的问题、或用户说"沉淀一下"时使用。
---

# /sediment — 引导式沉淀流程

依据:`knowledge/SEDIMENTATION-STANDARD.md`(铁律)+ `docs/kb-retrieval-contract.md` §2(schema)。
原则:**Agent 负责判重、脱敏、成文、生成 diff、验证和隔离提交；只有真实语义冲突、隐私边界
不明、外部发布或破坏性动作需要人作决定。不得把生成草稿或可审阅 diff 变成人工确认门。**

## 0. 角色模式(多端一致性:knowledge/ 单写者)

先判断当前角色(`.sulde-config.yaml` role 或用户身份):

- **协调端 / 单人项目**:走完整流程(§1-§4),唯一有权取号、写 `knowledge/`、提 PR
- **Dev 端**:只走 §1-§2 + 起草——把脱敏草稿(含判重检索结果)写入本任务 handoff 的
  `## 沉淀候选` 段,**不取号、不创建 knowledge/ 文件、不提 PR**;由协调端收 handoff 后
  统一判重、合并多端视角、入库

原因:判重检索只能看见已合入并重建索引的内容,并行直写会绕过查重且产生编号竞争;
单写者使沉淀串行化,dev 的根因细节与协调端的跨任务视角在同一条目合并。
漏网碰撞由机械兜底转为显式失败:doc_id 唯一性 lint + INDEX.md 合并冲突。

## 1. 收集素材

先按 `templates/knowledge/problem-card.md` 建 **Layer1 原始问题卡**。从当前对话、任务
handoff、日志或记忆原文提取；缺什么一次问齐，不能从常识补写成一手事实：

- **问题语境**：任务目标、用户真实预期、触发场景、可观察症状、期望与实际差异；
- **诊断证据**：根因、已排除假设、一手证据、修复/正确做法及验证；
- **证据状态**：`verified` 或 `inconclusive`。`inconclusive` 必须写缺哪项证据；
- **平台**：android / ios / flutter / harmonyos / web / cross / none；
- **四类样本**：路由正例、路由反例、执行合格例、执行失败例；每项都写判定原因；
- **样本来源**：逐项标 `observed`(真实出现)或 `constructed`(为划边界而构造)，不得把
  构造反例写成实测事故；
- 来源项目里的敏感细节清单(后面脱敏要删的)。

四类样本回答四个不同问题：

| 样本 | 必须回答 |
|---|---|
| 路由正例(`apply`) | 什么输入应召回/启用这条知识 |
| 路由反例(`skip`) | 哪个最相似输入不应召回/启用 |
| 执行合格例(`pass`) | 做到什么才算真正解决 |
| 执行失败例(`fail`) | 什么结果看似完成但仍违反不变量 |

## 1.5 分流判定:这条内容属于沉淀还是会话记忆?

沉淀(本 skill)只收**跨项目可复用、可脱敏通用化**的知识。以下情况**留在 Sulde
项目记忆**(会话自动捕获，必要时用 `memory_annotate` 标关系),不进 knowledge/:
- 项目特有状态:做到哪了、本项目的决策与理由、待办、环境配置
- 无法脱敏仍有价值的内容(细节即价值,通用化后就空了)
- 未经验证的猜测/单次现象(等复现或根因确认后再沉淀)。只有“已确认当前证据不足，且
  不确定性本身可复用”的内容可标 `inconclusive` 入库；`inconclusive` 不是猜测通行证

判据一句话:**过得了"脱敏+通用化"测试的进 KB,过不了的进 cognee**。
两边都值得的可以都做(Sulde memory 记项目版细节,KB 沉通用版)。

**对外分享文档不在本 skill 管辖内**:用户要的是"写一份拿出去分享的文件"时,
那是普通交付文档——写到项目交付目录,不进 knowledge/、不建 frontmatter、不走判重。
若文档中含通用工程内核且用户愿意,**另行提炼**一条 KB 条目(叙述与规则是两个
工件,不算重复存储;向量库只索引 knowledge/,分享文档与它零交互)。
KB 既有条目要外发时直接分享该 md(天生脱敏自包含),需要时去掉 frontmatter。

## 2. 判重检索(强制第一步)

用症状和根因各查一次:

```bash
SULDE_KB_INDEX="${SULDE_HOME:-$HOME/.sulde}/bin/kb-index"
"$SULDE_KB_INDEX" search "<症状描述>" -k 5 --json
"$SULDE_KB_INDEX" search "<根因关键词>" -k 5 --json
```

(索引未建则先 `kb-index build`;仍不可用退化为查 `knowledge/INDEX.md` + grep。)

Agent 读取候选原文后按下表作出可审计判定，并在结果中展示 doc_id、分数、标题、证据和理由：

| 信号 | 判定 | 走 |
|---|---|---|
| top1 ≥ ~0.75 且读原文确认**同根因** | 已有条目的变体/深化 | §3A 并入 |
| 相似度中等、同主题**不同根因** | 系列成员 | §3B 新增 + `related` 互链 |
| 均为低分 | 全新知识 | §3B 新增 |

判定前**必须 Read 候选原文**,分数只是线索,同根因与否看内容。

判定与续行规则：

- 证据充分且同根因：Agent 直接生成并入 diff、运行校验并在隔离分支提交；不要求用户回复口令。
- 证据充分且不同根因：Agent 直接按系列新增或全新条目处理。
- 证据不足：标 `inconclusive` 并保留原始候选，不写成事实，也不阻塞同批其他确定项。
- 只有两个以上语义方案均合理且会改变知识结论，或脱敏/隐私边界无法从证据判断时，才向人询问
  那一个具体选择；用户自然表达即可，Agent 负责把决定落实到文件和命令。

## 3A. 并入更新(不产生新编号)

1. Read 目标文件全文。实质合并时把目标升级到 `sedimentation_schema: 2`，按对应容器
   模板补齐问题原型、证据、适用边界与四类样本；只补 `related` 反向链接不要求迁移
2. `doc_id`/编号/文件名**不变**;若条目语义变宽,更新 frontmatter `summary`
3. 新变体涉及其他条目时在 frontmatter `related` 补链；已有样本不得被新样本覆盖，
   应合并为多例并保留各自 `observed|constructed` 来源

## 3B. 新增

1. **定容器**:单点错误→`anti-patterns`;平台事实→`platform-kb/{platform}/`;通用原则→`tech-docs/`;深复盘(⭐⭐⭐⭐+ 或强可移植)→`tech-docs/案例研究/{域}/`;工作法→`work-model/`
2. **反模式取号**:读 `knowledge/INDEX.md` anti-patterns 节最后一条编号 +1(append-only,空号不回填);文件名 `NNNN-kebab-slug.md`(slug 用通用化英文词)
3. **脱敏检查表**(逐项过,SEDIMENTATION-STANDARD §3):
   - 删:项目名/包名、commit/分支/MR、类名/路径/行号、页 ID/PRD§、业务功能名、人名/日期、内部文件引用
   - 留:方法论词(协调端/Dev/task md/MVI/TCA/SSE/baseline/平台名等)
   - **案例研究更严**:方法论词也不用,只留项目无关工程内核
4. **按容器成文**：统一 schema 真值是 `templates/knowledge/schema.json`，具体模板为：

   | 容器 | 模板 |
   |---|---|
   | anti-patterns | `templates/knowledge/anti-pattern.md` |
   | platform-kb | `templates/knowledge/platform-kb.md` |
   | tech-docs | `templates/knowledge/tech-docs.md` |
   | case-studies | `templates/knowledge/case-studies.md` |
   | work-model | `templates/knowledge/work-model.md` |

   模板固定的是语义角色和 `apply/skip/pass/fail` 契约，不限制段落、列表或表格形态。
   新文档必须带 `sedimentation_schema: 2`、受控 `problem_type`、
   `evidence_status`，并包含问题原型、根因与证据、适用边界、四类样本、正确做法、
   消费与防复发。任何必填段不得保留 `<占位符>`。

5. 若属系列:新条目 `related` 指向系列成员,并在最相关的老成员 frontmatter 里补反向链接

## 4. 收尾(固定四命令 + 呈现)

**先 `git add` 新增文件**——语料口径是 git-tracked,未 add 的新文件会被
lint/INDEX/索引三者静默忽略(实战踩过:自检索查不到才发现)。

先解析**可写的正典 Sulde Git checkout**（`SULDE_SOURCE_ROOT` 或用户明确给出的仓库根）；
不得把插件缓存/发布 runtime 当作可合并真值。然后在该根目录执行：

```bash
python3 "$SULDE_SOURCE_ROOT/scripts/kb/lint-frontmatter.py"
python3 "$SULDE_SOURCE_ROOT/scripts/kb/lint-sedimentation.py"
python3 "$SULDE_SOURCE_ROOT/scripts/kb/build-index-md.py"
"$SULDE_KB_INDEX" build
```

四者全绿后，Agent 在隔离审稿分支提交，并给用户看 `git status`、提交和 diff 摘要。任务范围已包含
推送/PR 时由 Agent 继续执行；需要外部发布授权时走宿主原生 Allow/Deny，不让用户复制命令。
用路由正例和路由反例各跑一次 `kb-index search`：正例应命中且可应用，反例不得被自动注入；
执行正负例交给实际消费者的回归测试验证。
