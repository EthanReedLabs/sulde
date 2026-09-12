---
name: record-prd-supplement
description: 甲方需求补充自动登记流程。当用户说"甲方补充 / PRD 增加 / 新增需求 / 补充需求 / 甲方又说 / 客户提了 / 需求补一下 / record this 等"触发词时自动启动,把新需求落到 4 处文档(PRD / UI 行为契约 / pen-truth / yaml),保证两端 /ui-impl 都能看到。每次甲方临时口头补充都用本流程,避免需求只存在主会话历史里漂移丢失。
user-invocable: true
---

# 甲方需求补充登记流程(协调端)

**目的**:甲方临时补充的需求(口头/微信/会议口令)只存在主会话历史会丢失,必须在第一时间落到**真相文档**。

**触发**:用户消息含以下任一词 → **不管上下文有多长立即启动本流程**:

- "甲方补充" / "甲方又说" / "客户提了" / "客户改了"
- "PRD 增加" / "PRD 新增" / "需求新增" / "需求补一下"
- "新增需求" / "补充需求" / "记一下需求"
- "把这个记下来"(且语境是需求补充,不是 bug 等)
- "/record-prd-supplement"

---

## 7 步流程

### Step 1:理解需求 + 定位

读用户提供的需求描述,确定:
- **需求性质**:交互细节(行为)/ 视觉规则(UI)/ 业务流程(数据)/ 多端约定 / 文案 / 其他
- **关联 pageId**:如 `<page-a>` / `<page-b>` 等(从需求描述里推断,如"某入口页"→ `<page-a>`)
  - 不确定时**必须问用户**:"这个补充关联哪个页面?(看 page-relation.yaml 全部 pageId)"
- **触发场景**:用户/系统什么行为下生效

### Step 2:定位 PRD 对应章节

```bash
# 协调端先 grep PRD 找最相关章节
grep -n "^## \|^### " "<项目文档区>/PRD/<产品需求文档>.md" \
  | grep -i "{需求关键词}" | head -5
```

例:某入口相关 → 对应入口章节;某列表交互 → 对应交互章节;某多步骤流程 → 对应流程章节。

不确定时问用户:"PRD 里你认为最相关的章节是哪个?或者我直接加新章节?"

### Step 3:在 PRD 加补充节(产品需求真相)

加在对应章节**末尾**(不破坏现有结构),格式:

```markdown
### {补充节标题}(YYYY-MM-DD 甲方补充)

{简短描述 — 2-4 句话讲清楚甲方说了什么}

{实现要求或交互约定 — 列点式}

详细规则见 UI 行为契约 §X.Y。
```

**约束**:
- PRD 改动**必须标日期 + "甲方补充"标签**(便于审计)
- 简短(2-4 句),细节放 UI 行为契约
- 不重写现有 PRD 章节,只追加

### Step 4:UI 行为契约加细节(实现层规则)

在 `<项目文档区>/techspec/UI 行为契约.md` 合适章节加新子节(如 `X.Y`):

模板:
```markdown
### X.Y {规则标题}(PRD §X.Y 补充,YYYY-MM-DD 甲方追加)

{背景 1-2 句:同一设计稿/同一行为被复用 / 触发条件等}

| 场景 / 维度 | 触发 / 形态 | 视觉来源 / 实现位置 |
|---|---|---|
| ... | ... | ... |

**两端硬约束**:

| 端 | 一份实现 | 形态 A | 形态 B |
|---|---|---|---|
| iOS | `XxxView` | 整页 / fullScreenCover | .sheet 包裹 |
| Android | `XxxFragment` | 整 frame | BottomSheetDialogFragment |

**禁忌**(关联 §7.1 复用优先):
- ❌ 双 UI 重复实现
- ❌ 弹窗形态自改设计

**Cross-Ref**:`pen-truth/{pageId}.md §X` 同步标注本规则。
```

**约束**:
- 一定要列**两端硬约束**表(防 Dev 误读)
- 必有禁忌段(明确反模式)
- Cross-Ref 链接到 pen-truth

### Step 5:pen-truth/{pageId}.md 加 Cross-Ref(设计稿层)

在 pen-truth 文档**末尾**追加:

```markdown
---

## N. 复用/补充 Cross-Ref(YYYY-MM-DD 甲方补充)

{说明:本设计稿对应 X 种触发场景 / 行为补充}

| 场景 | 触发 | 形态 |
|---|---|---|
| ... | ... | ... |

详见 PRD §X.Y "{标题}" + UI 行为契约 §X.Y。

**两端实现 1 个组件**,宿主决定形态。**禁止做两套 UI**(违反 UI 行为契约 §7.1)。
```

**约束**:
- 用 N(下一空号,不和已有 §1-§10 冲突,通常 §11 起)
- 链接 PRD + 契约 双向追溯

### Step 6:page-relation.yaml 加 reuse-context / supplement-note(图谱层)

找到 pageId entry,加自定义字段:

```yaml
"<page-a>":
  ...
  reuse-context:        # 共享视觉的多触发场景
    - integral-page
    - <shared-modal>
  supplement-note:      # 简短甲方补充注解(可选)
    - "同视觉两形态:入口整页 / 功能拦截弹窗"
  ...
  source: ... + YYYY-MM-DD-甲方补充
```

**注意**:yaml 中文括号是全角 `（）`,Edit 工具有时匹配失败,**用 Python 脚本绕过**:

```python
python3 <<'EOF'
import re
path = "<docs-hub>/design/page-relation.yaml"
with open(path, "r", encoding="utf-8") as f: content = f.read()
old = '... 原文(全角括号)... '
new = '... 改后 ...'
if old not in content: print("未匹配,grep 实际位置:", content.find("锚点字符串"))
else:
    with open(path, "w", encoding="utf-8") as f: f.write(content.replace(old, new, 1))
    print("OK")
EOF
```

同时在 yaml `audit-log` 段末尾追加:

```yaml
- date: YYYY-MM-DD
  action: prd-supplement-record
  page: {pageId}
  by: coordinator
  source: 甲方口头补充 + 协调端 /record-prd-supplement skill
  note: |
    {一句话总结甲方补充内容}
    落到 4 处:PRD §X.Y / UI 行为契约 §X.Y / pen-truth/{pageId}.md §N / 本 yaml entry
```

### Step 7:输出摘要给用户

格式:

```
甲方补充已落 4 处文档 ✅

| # | 文件 | 改动 |
|---|---|---|
| 1 | PRD V3 §X.Y | {简述} |
| 2 | UI 行为契约 §X.Y | {简述} |
| 3 | pen-truth/{pageId}.md §N | {简述} |
| 4 | page-relation.yaml `<page-a>` 条目 | reuse-context + audit-log |

信息流闭环:甲方补充 → PRD → 契约 → 设计稿层 → 图谱
任何 Dev /ui-impl 看任一处都会被引导到同一组件实现。
```

---

## 关键约束

1. **只加,不改**:PRD/契约/yaml 现有内容**不重写**,只追加补充节(避免破坏审计)
2. **必标日期 + "甲方补充"**:每处都标 `YYYY-MM-DD 甲方补充`,便于将来回溯
3. **必有 Cross-Ref**:4 处文档之间相互引用形成闭环
4. **必有禁忌段**:明确反模式,防 Dev 误读
5. **yaml 全角括号问题**:Edit 工具匹配半角失败时**直接用 Python 脚本**,不要重试 Edit
6. **不动 PRD 现有章节**:只在末尾加补充小节,主体保留

---

## 触发不应启动本流程的场景

- ❌ 一般 bug 反馈("某卡片没渐变")→ 走 /ui-impl 修复流程
- ❌ Dev 主动反馈反模式("发现某图标用 SF Symbol 替代")→ 走 /postmortem
- ❌ 设计稿更新(.pen 改了)→ 走 /update-design
- ❌ 用户给 task 描述但没说"甲方"或"PRD"→ 走 /assign / /ui-impl

---

## 输出要短

- 摘要 4 列表 + 1 句信息流图
- 不展开每处改动正文(用户已经知道改了)
- 末尾问 1 个 follow-up 问题(若有 cross-page 影响,提醒 Dev 在哪些页要注意)

---

## 历史先例(参考)

- **某入口形态补充**(`<page-a>`):甲方说"某入口有 2 个触发场景共享同一设计",落到 PRD 对应章节 / 契约对应章节 / `pen-truth/<page-a>` 补充段 / yaml `<page-a>` reuse-context — 信息流闭环示范
