---
doc_id: "work-model/task-md-template"
container: work-model
platform: none
summary: "🚨 **本文件被 v2 取代,标记 stale** 协调端写 task md **必读真值入口** = `writin…"
---

# task md 模板与协调端 checklist(三端共享)— ⚠️ STALE v1(已废)

> 🚨 **本文件被 v2 取代,标记 stale**
> 协调端写 task md **必读真值入口** = `writing-task-md` skill(完整规则,含起草前 baseline 强制段)
> v2 简版模板:`task-md-template-v2.md`(short form,做对照用)
>
> 本 v1 文件**保留作早期实战沉淀历史档案**,不再作起草指引

---

> ~~协调端写 task md 时套用本模板。~~(已废,真值见 writing-task-md skill)
> 从早期实战中沉淀,固化"完工三步 + 必跑合并指令 + 自检"等模式。

---

## task md 标准结构(必含 9 段)

```markdown
---
title: <端> <核心动作>(<约束 / 范围短描述>)
date: YYYY-MM-DD
assignee: <Dev 姓名> (`git as-X`,<风格类型,如 架构型 / 基础设施型 / 简洁型>)
branch: dev/<who>/<slug>(从 develop 切)
capability_tier: <light / balanced / deep>  # v1 当代迁移注记;不再新增 provider 型号字段
工时: ~Nh
---

# 背景(必读)

<3-5 行说明:为什么做、依赖什么改动、需求来源(接口文档 §x / 反模式 §x.y)>

## 协调端前置 verify(已做)

<列协调端 grep verify 的真实路径 / 类名 / 字段,标"已遵守(不凭印象编)">

---

# 改动清单(N 步)

## Step 1 — <动作> (~Nmin)

<具体改动:文件路径 + 关键代码示例 + 字段约束>

**约束**:
- <Kotlin 习语 / Swift 习语 #x 引用>
- <字段必从接口文档 §x verify,禁臆造>
- <反模式约束>

## Step 2 — ...

...

---

# 验证流程

5 步通用流程见 `verify-build.md`。本 task 特化:

## 特化 1 — <如编译验证 / 单测 / 截图归档>

<具体命令 + 期望输出>

---

# 强制 handoff 客观证据

handoff:`.ai-workspace/handoff/<date>-<slug>-result.md`

必含 5 段:

## §1 — 改动文件清单 + 关键 diff

## §2 — 编译输出末尾 30 行(BUILD SUCCEEDED / SUCCESSFUL)

## §3 — <task 特化验证内容>(grep / 截图 / 日志)

## §4 — <实际产出 grep 验证 / 旧代码清除 verify>

## §5 — 主观结论 + N 条声明 + 完工三步

\`\`\`markdown
- [ ] <声明 1> ✅/❌
- [ ] <声明 2> ✅/❌
- ...

## 完工三步(强制,缺一不算闭环)

- [ ] 1. 代码 commit(用 git as-X 身份)
- [ ] 2. handoff 5 段已出
- [ ] 3. 合 develop + 删本地分支(必跑下方"完工合并指令")
\`\`\`

---

# 完工合并指令(代码跑完后**直接 paste 到本端 shell**,必跑)

\`\`\`bash
git checkout develop
git -c user.name="<Dev 全名>" -c user.email="<Dev email>" merge dev/<who>/<slug> --no-ff -m "merge: <短描述> 到 develop"
git branch -d dev/<who>/<slug>
\`\`\`

跑完合并指令才算完工三步全做,handoff §5 完工三步全 ✅。

---

# 禁止

- ❌ 臆造接口文档没有的字段
- ❌ Mock 用假 domain(用 picsum.photos / soundhelix.com / Google 公开 mp3-mp4)
- ❌ <task 特定禁止项>
- ❌ **跳过完工三步**(具体提醒前面踩过的 Dev)

---

# 完工判定

handoff 5 段全有 + <task 特化条件> + 编译 SUCCEEDED + N 条声明全 ✅ + **完工三步全做** → 闭环。

合 develop + 删本地分支。

---

# 关联

- <接口文档 / 设计稿 / 反模式 §x.y / 历史改动引用>
```

---

## 协调端写 task md 时 checklist(写完前自检)

| # | 自检项 | 反模式引用 |
|---|---|---|
| 1 | frontmatter 含 title / date / assignee / branch / capability_tier / 工时 | 多宿主能力档策略 |
| 2 | "背景"段含"协调端前置 verify(已做)" — 列具体 grep 验证的真实路径 / 类名 / 字段 | 协调端凭印象编 |
| 3 | "改动清单"每 Step 含"约束"段,引用编码原则集习语 / 反模式 §x.y | 无 fallback + 任务粒度 |
| 4 | "验证流程"段含"5 步通用流程见 verify-build.md"(不复制内容,引用)| 反 DRY |
| 5 | "强制 handoff 客观证据"段必含 §1-§5(改动 + 编译 + 特化 + grep + 声明) | handoff 客观证据 |
| 6 | §5 末尾**必含完工三步声明**(commit / handoff / merge develop) | 完工三步 |
| 7 | "完工合并指令"段(代码跑完后直接 paste 的 bash 命令)| 完工三步仪式化 |
| 8 | "禁止"段含具体反模式编号引用 | 多 |
| 9 | "关联"段含接口文档 / 反模式 §x.y / 前序改动引用 | 知识链路 |
| **10** | **双端 task(同一需求双端跑)→ 必列"双端 Spec 层组织清单"硬约束(类名 / 文件路径 / method 签名),禁 Dev 自由判断** | **双端 Spec 组织未硬约束 → Dev 分化** |

### 双端 task md 必含"Spec 层组织清单"(硬约束)

涉及 Spec / Service 层(协议接口 / 数据模型 / 文件组织)的双端 task,协调端必先列双端清单 + 同名同 method 签名,**双端 task md 都嵌入同一份清单**,Dev 严格按清单写不自由判断:

```markdown
## 双端 Spec 层组织清单(协调端预先列,Dev 严格遵守)

| 模块 | iOS 文件 / 类名 | Android 文件 / 类名 | method 签名 | 数据模型 |
|---|---|---|---|---|
| 某创建规则 | `Sources/Spec/XxxClient.swift` | `core-spec/.../XxxService.kt` | `getXxx()` / `getXxxDetail(uuid)` | XxxDetail / XxxInfo |
| 某通知模块 | `Sources/Spec/InboxClient.swift` | `core-spec/.../NotificationService.kt` | `listFeed / markAsRead / unreadCount` | NoticeBanner / NoticeFeed |
```

Dev 实施时严格按清单 file 路径 / 类名 / method 签名命名,不自由发挥。

handoff §4 含双端字段 diff verify(协调端 audit 时机械检查双端一致性)。

**禁忌词**(协调端写双端 task md 时禁用,会触发 Dev 自由判断):
- "Dev 自己判断 / 自己 grep 决定 / 视情况"
- "扩展现有 Service OR 新建独立 — Dev 选"

正确表达:**"按清单严格写"**。

任一缺失 → task md 不合格,重写。

---

## 不同 task 类型的特化建议

### UI 实施 task(节点属性对照)

- 改动清单含 pen-truth 节点对照表(节点名 / 关键属性 / 实施值)
- 验证特化:**simulator/真机 5 步流程 + 截图归档**(参 verify-build.md)
- handoff §3 含截图 + 视觉差异自述
- 禁止:固定 dp / wrap_content,必须 aspectRatio

### 接口对接 task

- 改动清单含字段对照表(模型 / 接口文档 §x / 状态)
- 验证特化:编译 + grep 验证字段名 + 双端 diff(协调端职责)
- handoff §3 含 BuildConfig / .app 时间戳验证
- 禁止:臆造字段 / Mock 假 domain

### 架构 / 基础设施 task(跨依赖必拆)

- 范围明确(不跨依赖)
- 验证特化:编译 + 异常预案(当前能力档跑卡时升级到 `deep`)
- handoff 含设计决策记录(为什么这么改,verify 真实状态)

### 自发修小 bug(边界)

- 协调端不写 task md,口头让 Dev 走 mini-checklist(self-fix-boundary.md)
- Dev 命中敏感清单 → handoff 协调端,协调端再写 task md

---

## 历史踩坑教训(写 task md 前先 review)

- 任务粒度过粗 → 单 task 跨 5+ 模块,重写
- handoff 流于声明 → 必含客观证据(编译输出 / 截图 / grep)
- 节点对照只列名 → 必含属性(cr / fill / stroke / 字号 / aspectRatio)
- fallback 口子 → 禁忌词:TODO / 占位 / 暂时 / 视情况 / 可能
- 自发修复扩散 → 敏感清单 STOP
- 协调端凭印象 → 必先 grep verify 真实文件
- 完工三步漏 merge → task md 末尾必跑合并指令 + 强提醒

---

## 维护规则

- 协调端管辖,Dev 端只读
- 每次写新 task md 用本模板
- 实战中发现新踩坑 → 反模式集合 §3.x 登记 + 本模板更新
- 协调端 audit 时按本模板"checklist"机械检查 task md 合格度
