---
doc_id: "ap-0045"
container: anti-patterns
platform: none
summary: "0045 Dev 完成 task 但未走完\"出 handoff + 合主干 + 删分支\"完整闭环 → 协调端 audi…"
related: [ap-0220]
---

# 0045 Dev 完成 task 但未走完"出 handoff + 合主干 + 删分支"完整闭环 → 协调端 audit 时状态不一致

- **平台**:Dev(完工流程类)
- **复发次数**:7+

## ❌ 错误现象

| 实例 | 流程瑕疵 |
|---|---|
| 实例 A | commit + merge 主干 ✅,但**没出正式 handoff**(违反客观证据规则)。协调端 audit 时只能从 commit diff 推断改动是否符合 task md |
| 实例 B | commit + 出 handoff ✅,但**没合主干**(分支留未 merge)。协调端 audit 看主干时缺这个 commit,以为没跑 |
| 实例 C(三连) | 3 task commit + merge 主干全做了,3 份 result handoff 全没出 — 协调端 audit 反推自 git log + diff |

**为什么错**:
- task md 标准流程要求 "**出 handoff + 合主干 + 删本地分支**" 三步全做
- Dev 完成代码层面工作后,**漏掉中间一步**(handoff OR merge)就走人
- 协调端事后 audit 时**状态不一致** — 真完工但表面看像没完工 / 完工但缺证据
- 复发原因:简单 task 跑得快,handoff 这一步被 Dev 当作"可选"

## 为什么错(根因)

- 客观证据规则是 handoff 证据(证明真做了),本条是流程闭环(证明走完三步)
- 反复违规说明"完工"概念在 Dev 端不是"代码改完",而是"三步全闭环"
- 协调端工具链(audit 脚本 / capability-matrix)依赖主干状态,分支没合 → 工具链看到的状态错

## ✅ 正确 — 三步硬绑,缺一不算完工

**完工三步**(标准流程,缺一即违规):

```
Dev 完成 task:
  1. ✅ 代码改动 commit
  2. ✅ 出 handoff(`.ai-workspace/handoff/<date>-<slug>-result.md`,含客观证据)
  3. ✅ 合主干 + 删本地分支(`git checkout <main> && git merge --no-ff && git branch -d`)
```

### a. task md 在"完工判定"段显式列三步

```markdown
完工三步全做才算闭环:
1. 代码 commit(用对应身份)
2. handoff 5 段出在 .ai-workspace/handoff/<slug>-result.md
3. 合主干(git merge --no-ff)+ 删本地分支(git branch -d)

任一步漏 = 违规,协调端 audit 不通过,要求 Dev 补完缺失步骤后再算闭环。
```

### b. 子端 CLAUDE.md / shared-rules self-fix-boundary mini-checklist 加第 6 问

```
6. task 跑完后,完工三步全做了吗?(commit / handoff / merge 主干+删分支)
```

### c. 协调端 audit 时机械检查

```bash
ls .ai-workspace/handoff/<slug>-result.md            # handoff 存在
git log <main> --oneline | grep <slug-keyword>       # commit 已合主干
git branch | grep dev/<who>/<slug>                   # 应 0 命中(分支已删)
```

任一缺失 → 通知 Dev 补,**不通过**。

## 加固方案

1. **task md frontmatter 必含 `expected_handoff:` 字段**(预声明 result handoff 路径):
   ```yaml
   expected_handoff: .ai-workspace/handoff/<date>-<task-slug>-result.md
   ```
2. **task md "完工合并指令"前显式插入 hard alert**:
   ```markdown
   ⚠️ 复发警告 — handoff 5 段缺失 = 直接违规。
   不出 handoff 就 merge 主干 = 协调端 audit 必反推 + 复发计数 +1。
   ```
3. **协调端 audit 自动化**:`scripts/audit-handoff.sh {date}` — 扫主干自 {date} 起新合 commit,对照 handoff/ 文件存在性,缺失即报告

## 违规处理

- 漏 handoff:派"补 handoff" 微 task(Dev 30 分钟内补)
- 漏 merge:协调端给 Dev 派 merge 指令(可在原 handoff 末尾加 "合并指令" 段直接复制贴)
- 漏删分支:同上,加 `git branch -d` 步骤

## lint 状态

- Dev 工作流类,无静态扫描 → task md 完工判定段三步显式 + audit 脚本机械验
