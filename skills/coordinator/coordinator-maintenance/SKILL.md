---
name: coordinator-maintenance
description: 协调端周期性维护 + handoff 处理规则。当用户说"做下 audit / 周期审计 / 处理 handoff / 维护 page-relation / 检查反模式 / sweep handoff / 框架脚手架更新"等触发词,或协调端开始处理 Dev handoff / 跑反模式 audit / 更新 page-relation.yaml / 改框架脚手架规范时必 invoke。覆盖:反模式集合周期审计 / 框架脚手架规范维护 / 页面关系图谱维护 / 处理两端 handoff 文件 4 大子流程。CLAUDE.md 多个维护类规则的真值副本。
user-invocable: true
---

# 协调端维护类规则(4 子流程)

> 协调端做以下任一动作前必 invoke:处理 Dev handoff / 周期 audit / 更新 page-relation / 改框架脚手架规范。

---

## §1 页面关系图谱维护

**文件**:`<docs-hub>/design/page-relation.yaml`
**角色**:本项目所有页面(一级 / 二级 / state / modal)的**显式关系声明**。两端 `/ui-impl` skill 的阶段 0 必读,用来避免"A 改成 B"的误操作。

### 何时更新

协调端每次跑 Pencil MCP `get_editor_state` / `batch_get` 新页面时,对比 .pen top-level frames 与 yaml 条目差异:

- ⚠️ .pen 里有新 frame、yaml 没登记 → 加条目(parent / type / entry / children / android / ios / source)
- ⚠️ yaml 登记的页面 .pen 找不到对应 frame → 删条目 + 在 audit-log 记原因

其他触发:
- 两端终端通过 handoff 转交「图谱缺项需补」的请求 → 按 handoff 填 file 路径
- 两端发现某页从 page 变成 modal(或反之)→ 改 type
- 新增 state 分支 → 在宿主条目的 `states` 段加键

### 更新原则

1. **每条关系带 source 字段**(prd / design / heuristic / user-confirmed),便于审计追溯
2. **type 字段慎选**:page / modal / state / dialog 四选一,不要臆造
3. **state 分支**必须标 `state-of`,路径不要写"新文件"而是"同 X(同 View 不同分支)"
4. **status 字段**诚实填:clear / review-needed / todo,不要为了完整硬填 clear
5. 改完在 `audit-log` 段追加一条记录(date / action / page / by / note)

### 与反模式集合审计合并

周期审计时(见 §2),一并扫 page-relation.yaml:
- 所有 `status: clear` 的条目,android.file / ios.file 字段的文件在磁盘上必须真存在
- 所有 `status: todo` 的挂了超 30 天 → 派任务给对应终端催补
- 所有 `type: state` 的宿主 `state-of` 必须指向一个真实 page 条目

---

## §2 反模式集合周期审计

**机制**:两端 `/postmortem` skill 负责每次 bug 修复的登记;协调端负责**周期性审计**,防止两端 lint 漂移。

**审计频率**:每次用户在协调端做 review 工作时顺手做一次;至少每周一次。

**审计清单**:

1. **跑 `bash scripts/anti-pattern-tools.sh lint-status`** 列所有反模式 ✅/⏳/❌/❓ 分布 +「⏳ pending(待 lint 化)」清单(反模式以 `反模式/{NNNN}-xxx.md` ADR 独立文件组织,不是单一聚合 .md)
2. **对每一条验证**:
   - Android 标 ✅ 的:`ls <android-frontend>/scripts/lint/rules/` 文件存在吗?
   - iOS 标 ✅ 的:`ls <ios-frontend>/scripts/lint/rules/` 文件存在吗?
   - 标 ⏳ TODO 挂了超过 **7 天**? → 立即派 task 给对应终端实施修复(**不能停在"登记完事"**:登记 ⏳ 不派 task → 不久后同坑再踩)
   - 标 ⏳ TODO 挂了超过 30 天(且从未派 task)? → 视为高风险,周期审计第一优先处理
   - 标 ❌ 的给了原因吗?没给 → 要求补原因
3. **跨端不对称**:Android 有 iOS 没(或反之)→ 评估另一端是否真该补,给出结论
4. **复发次数 ≥ 2 的条目**:说明 lint 不够强,建议加严;给对应终端派升级任务

**漂移处理模板**:

发现漂移时给两端的任务文件放在 `.ai-workspace/tasks/postmortem-audit-{date}-{rule-slug}.md`,内容包括:
- 反模式条目引用编号
- 当前状态 vs 应有状态
- 另一端已有实现的文件路径供参考(只读不拷贝)
- 期望的 lint 规则草稿(粗略伪代码)

---

## §3 框架脚手架规范维护

**文件**:`<docs-hub>/techspec/框架脚手架规范.md`
**角色**:定义本项目框架脚手架层的核心脚手架(Router / TopBar / 三态视图 / Toast / Dialog / BottomSheet / 下拉刷新 等)契约。**两端 Feature 开发必读**。

### 何时更新

1. 两端发现**跨页面重复造轮子**的脚手架(如"每页自己画 title bar")→ 补进本规范
2. 某条反模式反复出现在多个页 → 说明脚手架缺件,回本规范登记 TODO
3. 两端完成了本规范的 TODO 项(如某端做完统一 TopBar)→ 更新对应表格的"当前状态"列为 ✅

### 协调端主动巡检

周期审计时(和反模式集合、page-relation 审计合并):
- 扫本规范所有"当前状态"标 ✅ 的条目 → 对应 class / 文件必须真存在
- 扫所有 ⏳ TODO 挂了超 60 天 → 派任务给对应终端催补
- 本规范每次更新必在末尾「变更记录」段追加一行

### 禁忌

- ❌ Feature 模块私自造脚手架(如某 feature 自己画 title bar)→ 必须抽到公共 UI 层
- ❌ 本规范 TODO 项永远 TODO 不派任务(需周期审计催)
- ❌ 改本规范不写变更记录(失去审计)

---

## §4 处理两端 handoff 文件

两端通过 `.ai-workspace/handoff/` 目录把跨端内容转交给协调端(参见两端 CLAUDE.md「跨端边界」节)。协调端**必须**及时处理,否则 handoff 堆积 = 知识漂移。

### 扫描时机

- 每次被 Android/iOS 告知「请交给协调端」时立即处理
- 每次做周期审计时兜底扫一遍(同步反模式集合周期审计)
- 会话开始如果用户提到 handoff 即处理

### 扫描命令

```bash
ls <android-frontend>/.ai-workspace/handoff/ 2>/dev/null
ls <ios-frontend>/.ai-workspace/handoff/ 2>/dev/null
```

### 处理流程

读 handoff 文件 → 按内容分派:

| handoff 要求 | 协调端动作 |
|---|---|
| 追加反模式条目 | 协调端写 `<docs-hub>/techspec/反模式/{NNNN}-xxx.md` ADR(单文件,不是聚合 .md)|
| 派对端任务 | 协调端写对端 `.ai-workspace/tasks/{date}-{slug}.md` |
| **跨端派单请求**(Dev 写 `-dispatch-request.md` / `-{platform}-dispatch.md`)| **协调端审核 + 转 task md 派对端**(详 §4.1 SOP)|
| 合入源端 lint 分支 | 协调 Agent 直接调度源端 Agent 执行，或生成受管 task 工件；不让用户代跑 Git 命令 |
| 更新技术方案 | 协调端改 `<docs-hub>/techspec/*.md` |

### §4.1 Dev 跨端派单请求处理 SOP

Dev 端实施过程中发现"另一端需同款 fix"时(典型:一端闭环后实证另一端同缺),按跨端边界规则**不可直接派对端**(任务调度属协调端职责),但 Dev 可写 **`-dispatch-request.md` 格式 handoff** 给协调端,内容是"对端 task md 开箱即用素材"。

**典型 dispatch handoff 含**:
- 真值源引用(pen-truth + 改动定位)
- 本端实施参考(diff / file:line / 资源命名约定 / 文案 key 命名约定)
- **对端实证 read-only grep**(对端文件 file:line + 现状 + 实现指引)
- 文案译文表(若本端已译,对端可 cp)
- 建议 scope + 严禁项 + 估时
- 关键陷阱(如跨端颜色格式 RGBA↔ARGB 差异)

**协调端 SOP**:
1. **审核数据源**:对端实证段是否 read-only(Dev 不可写对端)+ 真值源是否齐(pen-truth + 两端实证 grep)
2. **审核 scope**:Dev 建议 scope 是否符合协调端职责判断 — 不该机械追加(数据源齐时不外推产品决策)
3. **审核陷阱**:Dev 揪到的跨端格式陷阱 / 命名陷阱 / SSOT 边界 — 必加入 task md `§Step N 关键陷阱` 段(防对端重踩)
4. **转 task md**:基于 dispatch handoff 素材写对端 `.ai-workspace/tasks/{date}-{slug}.md`,**注明来源 handoff** + 译文表 cp + 陷阱预警
5. **归档源端 handoff** + 派对端

**判定线**:
- ✅ Dev dispatch handoff 含跨端 file:line 实证 + 译文表 / 陷阱 → 高价值,协调端转 task 时可 ~90% 沿用
- ❌ Dev dispatch handoff 仅"提议派对端做 X"无具体素材 → 协调端必自补 baseline 实证 + 估时,不能机械转 task
- ❌ Dev 直接写对端源码 / 改对端 .ai-workspace → 命中跨端边界,STOP

**反模式关联**:
- 协调端机械追加产品决策的反模式 — 跨端 dispatch handoff 含"escalate 产品决策"建议时,协调端必先 verify pen-truth 数据源齐;齐则不外推
- 跨端颜色格式陷阱的反模式 — Dev dispatch handoff 含此类陷阱时,协调端必加入对端 task md `§Step N 关键陷阱` 段

### §4.2 归档前必沉淀 Layer1 知识库（修后必沉淀回路）

handoff 若是【完工 fix / bug 复盘】类（`-result.md` 或含工程根因 + 教训），**归档前必先沉淀到 Layer1 知识库**:

```bash
bash <docs-hub>/_bugbook/scripts/add-bug.sh --slug "<slug>" --date "<date>" --end "<frontend>" --keywords "<k1,k2>"
# 再手填该 bug md 的根因 / 教训 / 修复 commit
```

**沉淀是归档的前置条件**:先 add-bug 落 Layer1 → 再 mv 到 archive/。跳过沉淀直接归档 = 知识漂移（handoff 堆积、baseline §7 沉淀欠债上涨、Layer1 知识库冻结）。

**判定线（Gate2）**:完工类 handoff 未沉淀 Layer1 就归档 = 不合格;baseline §7 沉淀欠债持续上涨 = 本 gate 没执行的信号。
**例外**:纯跨端 dispatch-request / 派单请求类 handoff（无独立工程根因）可直接归档,不强制 add-bug。

### 处理完**必须**归档

把 handoff 文件移到源端的 archive 目录(保留审计痕迹,不删):
> ⚠️ 归档前先确认已按 §4.2 沉淀 Layer1（完工类 handoff）。

```bash
mkdir -p <android-frontend>/.ai-workspace/handoff/archive/
mv <android-frontend>/.ai-workspace/handoff/{date}-{slug}.md \
   <android-frontend>/.ai-workspace/handoff/archive/
```

### 禁忌

- ❌ 忽略 handoff → 知识漂移积累
- ❌ 删除 handoff 文件 → 失去审计痕迹
- ❌ 协调端跨界到源端改非 `.ai-workspace/tasks/` 的源码(源码始终由对应终端改,协调端只写公告栏)
- ❌ 漏把反模式里声明 ✅ 的 lint 文件合入 → 条目声明要和实际文件状态一致,用 ⏳ 表示待合
