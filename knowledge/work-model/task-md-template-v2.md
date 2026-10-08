---
doc_id: "work-model/task-md-template-v2"
container: work-model
platform: none
summary: "📍 **本文件是 reference 模板**(short form),**真值入口** = `writing-tas…"
---

# Task md 共享模板 v2(short form)

> 📍 **本文件是 reference 模板**(short form),**真值入口** = `writing-task-md` skill(完整规则,含起草前 5 步 baseline 强制段)
>
> 协调端写 task md 前**必读 writing-task-md skill**(skill 强制 + 拒生成机制);本 v2 模板做字段对照 + 短引用 + Dev 端 quick reference
>
> ❌ **禁止从本 v2 模板直接 copy 起草** — 跳过 skill baseline 段 = 协调端凭印象起草反模式复发

---

> 协调端写 task md **必参引此模板**。Dev / 协调端读 task md 知道公共流程在此,不在每个 task md 重复。

---

## §1 任务头部模板(每个 task md 必含)

```markdown
---
- 身份:{Dev 姓名}(`git as-{a|b|c}`)
- 分支:`dev/{name}/{slug}`
- capability_tier:**{light|balanced|deep}**
- 工时:~{N}h
- 优先级:**{P0|P1|P2}**(原因)
- 流程参考:`work-model/task-md-template-v2.md` §3+§4+§5
- 关联前置 task:(若有)`{path}`
---
```

---

## §2 任务正文(每个 task md 自由发挥 — 仅含此 task 特有内容)

- **背景**(2-3 行,引用甲方反馈 / 反模式 / pen-truth § / PRD §)
- **真值参考**(`pen-truth/{pageId}.md § / .png` / `verify-page.sh {nodeId}`)
- **实施**(契约要点 / 控件代码片段 — 公共 boilerplate 不重复)
- **此 task 特有反例**(本 task 易踩的具体坑)

---

## §3 4 层防护机制(共享段 — task md 不重复抄)

- **L1 真值** — pen-truth/{pageId}.md(协调端 Pencil MCP 重导,每控件 ≥ 5 属性)
- **L2 实施** — task md 给 SwiftUI / Compose 代码片段,Dev 复制粘贴禁凭印象
- **L3 像素 diff** — `verify-page.sh capture` 输出 JSON,< 5% PASS / 5-10% 协调端确认 / > 10% 必再改
- **L4 多模态 review** — 协调端 Read 真机截图 + pen-truth.png 列偏离控件

---

## §4 标准实施流程(verify task 通用 — 用 verify-page.sh)

```bash
# 1. 构建 + install + launch
bash _scripts/verify-page.sh prepare {ios|android} {udid}

# 2. ⚠️ 用户手动导航到目标页 → 报"到了"

# 3. 截图 + L3 像素 diff
bash _scripts/verify-page.sh capture {ios|android} {pen-truth-png}
# 输出 JSON: {build, screenshot, diff_pct, passed, decision}

# 4. 决策 commit / handoff
bash _scripts/verify-page.sh commit {ios|android} {git-name} {git-email}  # 若 PASS
```

详 `_scripts/verify-page.sh --help`。

---

## §5 标准反例清单(共享段 — task md 不重复抄)

### 通用(所有 task)
- ❌ git add . / git add -A(可能误加 .ai-workspace 等)— 必显式路径
- ❌ commit message 含 AI 痕迹("Phase / 批次 / P0 / 经过分析 / emoji")
- ❌ scope 扩散(单 commit ≥ 3 文件 OR 跨 ≥ 2 module)— 命中敏感清单 STOP
- ❌ 编译用 swift build 验证含 UIKit 代码 — 必 xcodebuild
- ❌ 漏 ENABLE_DEBUG_DYLIB=NO(旧 iOS 真机 SIGTRAP)
- ❌ 偏差 > 5% 仍硬 commit(违反 L3)
- ❌ 不让用户手动导航直接截 launch 屏(diff 必全红误判)

### task 特有反例(在每个 task md 单独列 ~5 条)

---

## §6 完工三步预授权(共享段 — task md 引用,不抄)

```bash
# 仅当 verify-page.sh capture 输出 passed=true 时跑

git add {改动路径白名单}
git -c user.name="{Name}" -c user.email="{git-email}" \
    commit -m "{拟人化短句}"
git checkout develop
git -c user.name="{Name}" -c user.email="{git-email}" \
    merge dev/{name}/{slug}   # 不加 --no-ff，fast-forward 保持线性历史
git branch -d dev/{name}/{slug}

# iOS 完工 +1:真机 reinstall(自动)
# Android 完工 +1:adb install -r(自动)
```

---

## §7 handoff 模板(共享段 — Dev 写 handoff 引用此模板)

详 `_scripts/handoff-template.md`(short form,~30 行)。

---

## §8 协调端写 task md 5 步审单(协调端 task md 写之前必跑)

| Step | 内容 | 防的反模式 |
|---|---|---|
| 1 | Read pen-truth/{pageId}.md + .png(多模态识图)| .pen 节点不导 .png 凭文字猜 |
| 2 | grep PRD INDEX § + API SPEC INDEX | 单维度数据源 |
| 3 | Read 双端当前实现 + git log -5 + audit 双端进度 | 双端 Spec 组织未硬约束 |
| 4 | WebFetch / WebSearch 技术真值(框架 bug)| 凭印象 / 凭命名假设 |
| 5 | task md 含 3 段:① 3 维对照表 ② 反例 ③ escalation 候选预登记 | 协调端凭印象 |

---

## §9 派单短指令(协调端给用户)

先确认**目标 session 的当前宿主、当前模型、当前推理档**,再按
`model-strategy.md` 把 `capability_tier` 翻译为宿主原生指令。Claude Code 可使用
`/model <Claude 型号>` + `/assign`;Codex 使用 `/model`、`/reasoning` 选择器或直接保留
已满足要求的当前模型,最后写 `执行任务文件:.ai-workspace/tasks/{slug}.md`。禁止给 Codex
输出 Claude 型号名或 `/mode`。

---

## 历史

- v2 抽象出共享段(原每个 task md 重复 80% boilerplate → 缩到 50 行),配套 verify-page.sh 工具化。
