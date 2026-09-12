---
name: postmortem
description: Bug 修复沉淀 / 反模式登记 / postmortem / 复盘 / 4 问漏斗 / 加 lint 规则 — Bug 修完准备 commit 前走 4 问漏斗(踩过吗/会再踩/能 lint 化/其他端也有),自动生成反模式 ADR 条目 + lint 规则草稿 + 跨端 task md。当用户说"修完了想沉淀""走个 postmortem""复盘一下""加个 lint 规则""反模式登记"时触发,也由 /assign / /bug-hunt / /crash-fix 完工自动调起。stack 中性 — lint 写法 / 跨端镜像逻辑从 references/{stack}.md 读。
user-invocable: true
---

# Bug 修复沉淀(4 问漏斗)

修完 bug 准备 commit 前**必跑**本 skill。4 问漏斗 → 自动产出反模式 ADR / lint 规则草稿 / 跨端 task md。

**stack 决定后必先 Read 对应 references**:

| Frontend stack | 必 Read |
|---|---|
| `mobile-android` | `references/android.md` |
| `mobile-ios` | `references/ios.md` |
| `mobile-flutter` | `references/flutter.md` |
| `mobile-harmony` | `references/harmony.md` |

---

## §1 4 问漏斗

### Q1 — 以前踩过这个 pattern 吗?

```bash
grep -i "{关键词}" <docs-hub>/ADR/*.md
grep -i "{关键词}" <docs-hub>/反模式集合.md  # 旧 monolith 若仍存
```

- **命中** → 这是**复发**,在已有 ADR 增加 `recurrence: N+1` + 加新案例段 → commit message 用 `fix: ... §x.y`
- **未命中** → Q2

### Q2 — 会再踩吗?

判断条件:

- ✅ 复发型(必沉淀):同 pattern 多个 file 都可能踩 / 框架特性 / 团队习惯 / 跨 module 模板
- ⚠️ 边界型(可沉淀):看团队是否有 follow-up 类似实施
- ❌ 一次性(不沉淀):填错 URL / typo / 误操作 / 一次性配置

判定:**复发型 / 边界型 → 走 ADR 登记** + Q3;**一次性 → commit message 用 `fix: ... #once`**,跳过 ADR / lint。

### Q3 — 能不能 lint 化?

| 答 | 处理 |
|---|---|
| ✅ 能(可 grep / 静态检测 pattern)| 产出 `scripts/lint/rules/XXX-{slug}.sh` 草稿,`lint_status: drafted`,等审核后 `enabled` |
| ⚠️ 部分能(只能 grep 命中点提示,不能严判)| 产出 lint script + soft warning(5 秒延时不阻塞)|
| ❌ 不能(SwiftUI 类 / 行为型 / 设计判断)| `lint_status: infeasible`,**诚实标 "仅人工"**,不强造 lint |

stack 特定 lint 写法见 references/{stack}.md §1。

### Q4 — 其他 frontend 也有吗?

跨端镜像检查:

| 答 | 处理 |
|---|---|
| ✅ 其他 frontend 同 pattern 也存在 | 写 跨端 handoff `.ai-workspace/handoff/{date}-cross-frontend-{slug}.md` 给协调端,**handoff 必含**:本端复盘摘要 + 其他 frontend 文件路径 + 建议 task scope |
| ❌ 仅本 frontend 特有 | 在 ADR `platforms: [{当前 stack}]`,**不主动派其他 frontend** |

跨端镜像逻辑见 references/{stack}.md §2(列出其他 frontend 的同语义文件路径)。

---

## §2 自动产出物

跑完 4 问后,本 skill 产出:

1. **反模式 ADR 条目**(写入 `<docs-hub>/ADR/{NNNN}-{slug}.md` 或更新既有 ADR `recurrence`)
2. **lint 规则草稿**(若 Q3 == ✅,写 `scripts/lint/rules/{NNNN}-{slug}.{sh}` 或 stack-specific 脚本)
3. **跨端 handoff**(若 Q4 == ✅,写 `.ai-workspace/handoff/{date}-cross-frontend-{slug}.md`)
4. **commit message 模板**:`fix: ... §x.y` 或 `fix: ... #once`

---

## §3 commit message 规则

| 类型 | 标记 | 含义 |
|---|---|---|
| 复发型 / 已登记 ADR | `fix: ... §{NNNN}` | 自动引用,git log 自动成 ADR 索引 |
| 边界型 / 新登记 | `fix: ... §{NNNN}` | 首次登记 |
| 一次性 / 无沉淀 | `fix: ... #once` | 跳过 ADR / lint |
| 多个分类 | `fix: ... §{N1} §{N2}` 或 `fix: ... §{N} #once`(部分) | |

pre-commit hook 看到 `§` 或 `#once` → 放行;否则 5 秒软警告 + 提示跑 /postmortem。

---

## §4 不强制跑 /postmortem 的例外

- 新功能开发(不是 fix:)
- 纯重构(不是 fix:)
- 一次性误操作(填错 URL / typo)→ commit 加 `#once` 即可跳过 skill

---

## §5 ADR 写入格式(`<docs-hub>/ADR/{NNNN}-{slug}.md`)

```markdown
---
adr: "{NNNN}"
title: "{Bug pattern 一句话描述}"
platforms: [{当前 stack / any}]
first_logged: {date}
recurrence: 1   # 命中既有 ADR 时 N+1
lint_status: {drafted|shipped|infeasible}
---

# {NNNN} — {title}

**First logged**: {date}
**Platforms**: {当前 stack}
**Recurrence**: 1
**Lint status**: {status}

---

## Symptom
{现象一句话}

## Root cause
{根因}

## Cost
- {耗时 / 影响 / 隐患}

## Mitigation
### Short-term
- {fix 已经做的}

### Medium-term
- {规则 / 流程改进}

### Long-term
- {自动化 / lint / CI}

## Related
- 修复 commit: {hash}
- 关联 lint: `scripts/lint/rules/{NNNN}-{slug}.sh`(若有)

## Example incident
{本次案例匿名版本,关键细节}
```

---

## §6 lint 规则草稿模板

`scripts/lint/rules/{NNNN}-{slug}.sh`:

```bash
#!/usr/bin/env bash
# Rule: {NNNN} — {title}
# Status: drafted | shipped
# Stack: {android | ios | flutter | harmony | any}
#
# Symptom: {一句话}
# Pattern: {grep / AST 模式}

set -e

VIOLATIONS=$(grep -rn "{pattern}" {paths} 2>/dev/null | grep -v "{allowlist}" || true)

if [ -n "$VIOLATIONS" ]; then
    echo "❌ ADR {NNNN} violation:"
    echo "$VIOLATIONS"
    exit 1
fi
exit 0
```

详 stack-specific 写法见 references/{stack}.md §1。

---

## §7 跨端 handoff 格式

`.ai-workspace/handoff/{date}-cross-frontend-{slug}.md`:

```markdown
# 跨端 handoff: {slug}

## 本端复盘

- stack: {当前 stack}
- ADR: §{NNNN}
- Symptom / root cause / 修复: 详 ADR `<docs-hub>/ADR/{NNNN}-{slug}.md`

## 其他 frontend 镜像

{stack 列表,每个 frontend 1 段}:

### {other-stack-1}
- 同语义文件路径: {file path 1} / {file path 2}
- 建议 task scope: {fix 范围}
- 优先级: {高 / 中 / 低}

### {other-stack-2}
...

## 协调端动作

- 写 fix task md 给 {other-stack 1 dev}
- 写 fix task md 给 {other-stack 2 dev}
- 完工后跨端镜像 verify

(协调端跑 writing-task-md skill 起草)
```

---

## §8 与其他 skill 衔接

- `/crash-fix` → 修复完 commit 前 **自动调** /postmortem
- `/bug-hunt` → 同上
- `/assign` 跑 fix 类 task md → 同上
- 任何 `fix:` commit 前 → Agent 自动调用本 skill；pre-commit hook 仅作遗漏提醒，不要求用户手动输入 `/postmortem`
