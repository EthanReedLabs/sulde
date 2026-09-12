---
name: codex-preflight-scaffold
description: 协调端写 task md 前用 Codex MCP 跑两阶段 pre-flight — Phase A 反抽源真值端(如 Flutter)4 维真值(节点/数值/资源/行为)输出 truth.md;Phase B 基于 truth.md + writing-task-md SKILL.md 生成 task md scaffold 草稿。协调端单 session 不再吃源工程源码,context 余量翻倍,task md 写从 60-90min 降到 review 改 15-25min。触发词:"反抽 page X / 写 task md / Codex 试跑 preflight / 起 task md scaffold / 源真值 sweep"。
user-invocable: true
---

# codex-preflight-scaffold — Codex 两阶段 pre-flight: 反抽 audit + task md scaffold

> 占位符约定:`<source-stack>` = 源真值端 stack(设计/行为的一手真值源工程,如 Flutter / SwiftUI / 既有 Web);`<target-stack>` = 目标实施端 stack(如 HarmonyOS / Android / iOS);`<docs-hub>` = 文档/真值中心目录;`design-truth` = 设计真值(pen-truth 概念的通用名);`api-contract` = 接口契约目录。下文以 Flutter → HarmonyOS 为运行示例,任一 `<source-stack>` → `<target-stack>` 组合同理。

## §0 触发条件 + 何时不用(默认不用)

**默认行为:不用 Codex preflight,协调端直接手写 task md**。Codex preflight 是工具,不是流程默认 — 派 Codex 也有成本(prompt 时间 + token + review wall-clock + `.codex-out/` 累积),不是 free。

### 触发(全 3 项命中才跑,任一不命中 → 不用)

| # | 条件 | 自检 |
|:-:|---|---|
| 1 | **page 规模超协调端单 session 容量** | `<source-stack>` 主 page + controller + view + bindings 合计 > 500 行 OR > 4 file 跨依赖 |
| 2 | **真值穷尽度风险高** | 多 decoration 字段 / dual hex 配色 / dark variant asset / 多状态分支 / state-action-render 全链 — 任一漏 = Dev 返工 ≥ 2 rounds |
| 3 | **task 复杂度配 `deep` single-session** | per `writing-task-md SKILL §4` 能力档 8 问,本 task 评 `deep`(非 `balanced/light`)|

### 何时**不用**(默认场景)

- ❌ userfix / bugfix / spike(per `writing-task-md SKILL` 决策树 — Dev 直接处理)
- ❌ < 30 行 polish 类(纯 prop 微调 / 单点 fix)
- ❌ 协调端已熟悉的 page 结构(某已多次反抽过的列表/日历/设置页)
- ❌ `<source-stack>` widget tree < 200 行单文件(协调端手写更快)
- ❌ 已有 design-truth + 4 维真值清单全 + `<source-stack>` 原文 paste 已 ≥ 50 行 → 直接派单
- ❌ 简单 UI fix / dark mode hex 修正 / 单 asset 替换 / 单接口 query 修改

### 边界示例

| 场景 | 用 Codex preflight? |
|---|:-:|
| 某全模块数千行反抽 | ✅(超协调端容量 + 高复杂度 + `deep`)|
| 某设置模块 full reverse impl | ✅(跨多 file + 高穷尽度风险)|
| 某单页 AppBar polish(已 ship,甲方反馈微调)| ❌(单页已熟,协调端手做更快)|
| 某单 icon asset 替换 | ❌(单 asset 替换,协调端直接派单)|
| 新 page 首次反抽(协调端不熟 + 多 file)| ✅ |
| 简单 fix(文本改、margin 调)| ❌(能力档不匹配,`light/balanced` 直接干)|

---

## §1 Phase A — Pre-flight 反抽 audit(Codex 跑,role-play 协调端 agent)

### 输入

- `page_id`(eg `feed-tab` / `list-page` / `detail-page`)
- `<source-stack>` 主 page 文件 + controller + view 依赖清单(协调端列,Codex 自己 grep 补)
- 关联 design-truth nav map ref(若有)
- 关联前序 handoff(若 reimpl / 续接)

### 输出 `<docs-hub>/.codex-out/<page_id>-truth.md`

必含 9 段:

| 段 | 内容 | 防的反模式 |
|---|---|---|
| §0 文件清单 | Read 全 file 列 path + 行数 + git SHA | 防 stale Read / 漏 file |
| §1 节点树 | widget tree 完整 hierarchy(Scaffold→Column→...)标 file:line | 节点漏 |
| §1.5 数值表 | 逐字段:margin/padding/font/aspectRatio/threshold/颜色 hex/时长 ms,每行 file:line ref | 数值不 1:1(文本 layoutWeight 溢出类反模式)|
| §2 资源表 | asset 文件名 + dark variant + color token(light/dark hex 一对儿)| 资源漏(paste 真值不整块反例)|
| §3 行为表 | 条件分支/dialog/event/interaction state/storage key 读写 | 行为漏 + storage key 不对称(静默失效反模式)|
| §4 接口段 | 调用点列表(如 `DioManager.post`),区分 query param vs body,关联 endpoint 常量名 | POST 参数放错位置反模式 |
| §5 `<source-stack>` 原文 paste | awk 抽 ≥ 50 行完整 decoration/layout block(per `writing-task-md SKILL` paste 强制段)| 浅采 grep |
| §6 self-check | Codex 自答 5 问(全 file Read?4 维 ≥ 5 条+标 line?paste ≥ 50 行?dual hex 一对儿?asset dark variant 查?)| Codex 自跳步 |
| **§7 prompt 纠错段** | Codex 列协调端 prompt 里发现的 ≥ 0 处错(路径/类名/scope 描述/字段假设),每条标 prompt 引文 + `<source-stack>` file:line 真值 + 建议修正 | 高价值副产 — 防协调端错带进 Dev task md → Dev 返工(实测某全模块 trial 抓出 4 处纠错)|

### Phase A Codex prompt 模板(role-play)

```
你是本项目协调端反抽 agent。任务:对 page `<page_id>` 做完整 <source-stack> 真值反抽。

工作目录:<source-stack 主工作树绝对路径>(read-only sandbox)

必读 baseline:
1. ./CLAUDE.md(协调端规则 + 反模式)
2. <docs-hub>/sulde-skills/coordinator/writing-task-md/SKILL.md(4 维真值清单 + 原文 paste 强制段)
3. <docs-hub>/sulde-skills/coordinator/codex-preflight-scaffold/SKILL.md §1(本 Phase A 输出 schema)
4. <source-stack> page 目录全源文件完整 Read(page + controller + bindings + view 依赖)
5. <source-stack> 接口入口表 + 配置(endpoint 真值)
6. <source-stack> 本 page 相关 DTO

工作流程:
1. ls + git log -10 page 目录,列变更
2. 完整 Read 每个源文件(标行数),禁 grep 浅采
3. 按 SOP §1 输出 schema 9 段写入 `<docs-hub>/.codex-out/<page_id>-truth.md`
4. §1.5 数值表必含 `file:line` ref;§2 dual mode hex 必一对儿(light/dark);§5 paste 必 awk ≥ 50 行
5. §6 self-check 5 问全 PASS,否则不算交付
6. §7 prompt 纠错段(强制):Codex 主动列协调端 prompt 里发现的错(路径假设错 / 类名不存在 / scope 描述与代码不符 / 字段数量假设错 等);0 错也要写"§7 prompt 纠错:0 处发现"

铁律(违反 = 重写):
- 禁猜测 / 凭印象(本 task 主线就是反抽完整真值)
- 禁 grep 浅采替代 awk full block paste
- 禁跳 dark variant 查 / asset 命名核对
- 禁缩水到 < 50 行 <source-stack> 原文 paste
- 输出 markdown 文件,禁 inline 大段贴回我
- 禁吞 prompt 错 — Codex 即使 100% 顺利按 prompt 跑也要主动校验 prompt 假设 vs <source-stack> 真实代码,§7 段必出

完成后只回:文件路径 + §1.5 行数 + §5 paste 行数 + §6 self-check 5 问答案 + §7 prompt 纠错处数。
```

---

## §2 Phase B — task md scaffold 生成(Codex 跑,基于 Phase A 输出)

### 输入

- Phase A 输出 `<docs-hub>/.codex-out/<page_id>-truth.md`
- 协调端给的 task scope 描述(1-2 句:"还原某 tab 的 fade scroll + search box 1:1")
- 前序 handoff(若 reimpl)

### 输出 `<docs-hub>/.codex-out/<page_id>-task-scaffold.md`

必填 task md 全段(per `writing-task-md SKILL`):
- frontmatter(assignee / branch / capability_tier / worktree)
- §0 起草前 baseline 实证(5 步)+ **若 page 已有协调端既有 task md → §0 必 cross-ref + 标 v2 scaffold**
- §1 in-scope(Phase 1 主链路 / Phase 2 polish 划界)
- §1.5 4 维真值清单(直接 paste Phase A §1.5 + §2 + §3)
- §1.5b `<source-stack>` 原文 paste(直接 paste Phase A §5)— **§1.5b 单段头,不重复 paste Phase A §5 header**
- §2 当前 `<target-stack>` 现状(Codex grep 目标端既有实现写)
- §3 复用思考(≥ 5 条,标 tag 扩既有/新文件/内联,per `writing-task-md SKILL` 复用最小 scope 规则)— **新文件 tag 强制 `(可复用 N≥2 处)`,否则自动降级 `内联(1 次用)`**
- §4 verify steps
- §5 handoff path + 必含段清单
- §6 铁律
- **§7 A/B 校正表(仅当既有 task md cross-ref 触发时必填)**:列 v2 scaffold 与既有 task md 的具体差异(scope / cell 数 / file path / Phase 划界 等),每条标 `<source-stack>` file:line 真值依据

### Phase B Codex prompt 模板(role-play)

```
你是本项目协调端 task md 起草 agent。任务:基于 Phase A 反抽 truth,起 task md 草稿。

工作目录:<source-stack 主工作树绝对路径>

必读:
1. ./CLAUDE.md + <docs-hub>/sulde-skills/coordinator/writing-task-md/SKILL.md(全段)
2. <docs-hub>/sulde-skills/coordinator/codex-preflight-scaffold/SKILL.md §2(本 Phase B 输出 schema)
3. <docs-hub>/.codex-out/<page_id>-truth.md(Phase A 反抽真值)
4. <target-stack> 工程目录 grep 既有可复用 component(写 §3 复用思考用)
5. 协调端派单模板(`deep` single-session,目标宿主再翻译)

task scope:<user 给的 1-2 句描述>

工作流程:
1. 直接 paste Phase A §1.5 / §2 / §3 / §5 到 task md §1.5 / §1.5b(不重抽,协调端已审过)
2. §1.5b 单段头 — 不重复 Phase A `## §5 <source-stack> 原文 paste` header,直接接 paste body
3. grep <target-stack> 既有 component 写 §2 + §3
4. §3 复用思考 ≥ 5 条,每条标 tag(`扩既有 prop` / `新文件(可复用 N≥2 处)` / `内联(1 次用)`)— 新文件 tag N<2 时自动降级 `内联`
5. §1 必分 Phase 1 / Phase 2(per writing-task-md SKILL 划界规则)
6. 若 page 已有协调端既有 task md(tasks 目录 grep)→ §0 baseline cross-ref + §7 A/B 校正表必填,每条标 <source-stack> file:line 真值
7. 写入 `<docs-hub>/.codex-out/<page_id>-task-scaffold.md`

铁律:
- 禁原创 §1.5 真值(直接 paste Phase A)
- §3 复用思考 < 5 条 → 重写
- Phase 1/Phase 2 不划界 → 重写
- §1.5b 与 Phase A §5 双段头 → 重写
- 新文件 tag N=0 或 N=1 仍标 `新文件(可复用 N≥2 处)` → 重写
- 输出 markdown 文件,禁 inline 贴回我

完成后只回:文件路径 + §1 Phase 1 项数 + §3 复用条数 + tag 分布 + scope 自检 3 问答案 + §7 A/B 校正项数(若触发)+ §1.5b 单段头(yes/no)。
```

---

## §3 协调端 review checklist(对 Codex 两阶段输出)

### Phase A review(6 维 sniff test,≥ 2 ❌ 重跑)

| 维 | check |
|---|:--|
| 完整性 | §0 file 清单 vs 协调端预期 list,有漏吗?|
| 1:1 | §1.5 数值表抽样 3-5 行,对 `<source-stack>` file:line 实证 hit |
| dual hex | §2 light/dark 一对儿全填?|
| paste 真值 | §5 awk ≥ 50 行,decoration block 完整(不是 partial)|
| self-check | §6 5 问 Codex 自答全 PASS |
| prompt 纠错 | §7 必出(0 错也写"0 处"),≥ 1 处时协调端必采纳更新 Phase B prompt + 自查既有 task md |

### Phase B review(6 维)

| 维 | check |
|---|:--|
| truth paste | §1.5 / §1.5b 是不是 Phase A 原文 paste 不重写 |
| 单段头 | §1.5b 只 1 个 `## §1.5b` header,Phase A `## §5 <source-stack> 原文 paste` 不重复 |
| Phase 划界 | §1 Phase 1 主链路 vs Phase 2 polish 清晰 |
| 复用 ≥ 5 + tag | §3 每条标 tag + 新文件 tag N≥2 否则降级"内联" |
| scope 自检 | §0 5 步 baseline 实证段填了 |
| 派单 ready | §5 handoff path + 必含段都列了 |
| A/B 校正(若 cross-ref 触发)| §7 A/B 校正表填了,每条标 `<source-stack>` file:line 真值依据 |

---

## §4 反模式 / 何时降级

| 反模式 | 现象 | 降级 |
|---|---|---|
| Codex 跑 Phase A 出大段总结但漏文件 Read | §0 文件清单少于协调端预期 | 补 prompt: "列每个 file 行数 + SHA,缺一不可" |
| Phase A §5 paste < 50 行 | grep 浅采复发 | 重跑,prompt 加 `awk 'NR>=X && NR<=Y'` 示例 |
| Phase B §3 复用条数 < 5 | Codex 没 grep `<target-stack>` | 重跑,prompt 加 "必跑 grep 目标端工程" |
| Codex 输出 inline 贴回不写文件 | sandbox 模式没 workspace-write | 改 codex MCP `sandbox: workspace-write` |
| Codex drift 跑非 page 的 file | scope 漂 | prompt 加 "禁读 page 目录外 file"(除 SKILL.md baseline + 接口入口表)|

---

## §5 trial / verification protocol(首次跑用)

1. 选已 ship 的 task md 当 ground truth(某已 ship page 的 task md + 完工 handoff)
2. Phase A → 输出 `<docs-hub>/.codex-out/<page_id>-truth.md`
3. 协调端用 §3 Phase A review 6 维对照 ground truth handoff §2 `<source-stack>` Truth Table
4. Phase B → 输出 `<docs-hub>/.codex-out/<page_id>-task-scaffold.md`
5. 协调端用 §3 Phase B review 对照原 task md
6. 量化 ROI:
   - 时间:Phase A+B Codex wall-clock vs 协调端手写 60-90min
   - 质量:Codex §1.5 行数 vs ground truth handoff 里 fix 修正项(漏字段数)
   - context:协调端本 session 没 Read `<source-stack>` 源码大段 → context 余量 vs 历史
7. 试跑结果写 retrospective 到 `<docs-hub>/.codex-out/_retro-<page_id>.md`

---

## §6 Codex MCP 调用方式

```
mcp__codex__codex(
  prompt: <§1 Phase A prompt 模板,填 page_id + scope>,
  cwd: "<source-stack 主工作树绝对路径>",
  sandbox: "workspace-write",
  approval-policy: "on-failure",
  model: <codex 模型 id 或 default>
)
```

Phase B 用 `codex-reply` 续接 same threadId(保 Phase A context):

```
mcp__codex__codex-reply(
  threadId: <Phase A 返回 threadId>,
  prompt: <§2 Phase B prompt 模板,填 task scope>
)
```

---

## §7 trial ledger + 累积 patch(可选,防拍脑袋)

每跑一个 trial **落 retro 文件 + 更新 ledger**,累积到阈值再统一 patch 本 SOP,否则无凭据 → patch 拍脑袋。

**retro 文件路径**:`<docs-hub>/.codex-out/_retro-<page_id>.md`(下划线开头 → ledger 跟 truth/scaffold 输出在文件名上一眼区分)

**retro 必含段**:
- 元信息(page / ground truth ref / Codex model)
- Phase A 量化表(9 段 schema 项)
- Phase B 量化表(scaffold 段)
- ground truth 命中表(✅/❌ 字段对比)
- SOP 改进项观察(哪几项本 trial 应用/暴露)
- Verdict + 下一步

**ledger 文件**:`<docs-hub>/.codex-out/_trials-ledger.md` — 一行一 trial,聚合状态判 patch 触发。

```markdown
# Codex preflight SOP trials ledger

| # | Page | Retro file | Phase A 行 | Phase B 行 | Self-check | Prompt 纠错 | 应用改进项 | Verdict |
|:-:|---|---|--:|--:|:-:|:-:|---|:-:|
| 1 | ... | ... | ... | ... | ... | ... | ... | ✅/❌ |
```

**patch 触发**:ledger ≥ 3 行 + ≥ 2 个 trial 标记同一改进项应用/暴露 → 协调端起 patch task。

---

## §8 关联

- writing-task-md SKILL — Phase B 写 task md 的 spec source(4 维真值清单 / 原文 paste 强制段 / Phase 划界 / 复用最小 scope / 派单模板)
- multi-source-review SKILL — Codex 输出 review 时复用 4 维表风格
- 反模式:paste 真值不整块(本 SOP 直接解决)/ 反抽穷尽度不足 / Codex MCP cwd 约束(Phase A read-only sandbox,Phase B 写 `.codex-out/` 非 worktree)/ subagent 输出可能截断(协调端必 ls `.codex-out/` + Read verify)
- 上游决策:反模式 0142(Codex preflight 触发门槛,本 SOP ship 后追)
