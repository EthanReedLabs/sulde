---
doc_id: "ap-0043"
container: anti-patterns
platform: none
summary: "0043 Dev 自发修小 bug 时改动范围扩散到敏感字段 → 协调端协作类防护被绕过"
---

# 0043 Dev 自发修小 bug 时改动范围扩散到敏感字段 → 协调端协作类防护被绕过

- **平台**:Dev(自发修复路径)
- **复发次数**:1

## ❌ 错误现象

- 用户口头报小 bug:"返回按钮重建界面"
- Dev 自发提交 `fix: 补某向导第 4 阶段 + 返回按钮不再重建界面`
- 真正的 bug fix(dismiss action + navigationDestination set)合理
- 但**顺手**改了某向导 `stageNames` 从 3 项变 4 项 / footer 从 "of 3" 变 "of N" / 加了两个新 stage
- = 把此前严格按设计真值实施的 3 stage 给"撤销"了,违反 pen-truth 真值

**为什么协作类防护没拦住**:
- 协作类防护全部假设"协调端写 task md → Dev 跑 task md"路径
- Dev 自发 commit(用户口头报 bug → Dev 直接修 → 不写 task md → 直接 commit)路径**完全没约束**
- task md 再严,管不到不走 task md 的 commit
- 协调端事后才在 git log 里发现 → 救火返工

## 为什么错

- "再加严 task md"只在 task md 路径生效,Dev 自发 commit 时全部失效
- 不能一刀切"禁止 Dev 自发 commit"(用户报小问题继续要让 Dev 直接修,提速)
- 真正问题是"修 X 小 bug 时改动范围扩散到 Y 大流程",不是"自发修复"本身
- 解法 = Dev 端拥有规则 cognition + 敏感清单 STOP 机制 → 多数小 bug Dev 自发,敏感改动 handoff 协调端

## ✅ 正确

Dev 端拥有"规则 cognition"(pen-truth 优先 / 敏感清单 / mini-checklist),但调度仍在协调端。

**敏感清单**(Dev 自发禁改,改这些必须 task md):

| 类别 | 具体内容 |
|---|---|
| **向导结构** | `stageNames` 数组项数 / `Step N of M` 文本(M 改动)/ 向导 step switch case 数 / step 路由 |
| **数据源切换** | Mock URL 大批替换 / API endpoint / Spec 接口契约 |
| **scaffold 层** | base Activity / 路由器 / 顶栏 / 颜色 token / 字体 token / 状态视图 / pen-truth 关键属性(fill/stroke/cr/字号 跨页统一) |
| **page-relation 类** | type 字段(page/modal/state)/ states 分支 / parent / next |
| **scope 扩散** | 单 commit 涉及 ≥3 文件 OR 跨 ≥2 Feature module |

**自发修复 mini-checklist**(Dev commit 前 5 问):

| # | 问题 | 命中处理 |
|---|---|---|
| 1 | 改的字段在敏感清单里吗? | 是 → STOP,handoff 给协调端写 task md |
| 2 | 涉及视觉/文案/stage 数 → Read pen-truth.md + .png 了吗? | 否 → 先读再改 |
| 3 | 改的范围是否只在原始 bug 内?(diff 文件数 / 行数 / 字段) | 否 → 拆 commit,无关改动单独走 |
| 4 | commit message 拟人化短句?(no Phase / 批次 / P0 / emoji) | 否 → 重写 |
| 5 | 一次性 或 沉淀型 标注? | 否 → 补一个 |

## How to apply

1. **子端 CLAUDE.md 加段「自发修复边界」**:列敏感清单 + mini-checklist;"命中清单 = STOP,改都不要改,先 handoff;其他自由修"

2. **Dev commit 前自检**(走 mini-checklist 5 问):命中 #1 敏感清单 → STOP;否则 #2-#5 全过 → 可 commit

3. **Dev 命中敏感清单时,handoff 给协调端**(不自己写 task md):
   ```markdown
   # handoff: 请协调端派 task — {bug 描述}
   - 触发场景:{用户在 X 终端报 Y bug}
   - 我看到的现象:{具体现象}
   - 命中敏感清单:向导结构 / data_source / scaffold / ...
   - 不自发修原因:命中敏感字段(具体哪个)
   - 建议改动范围:{我看到的范围,但不自动派}
   ```

4. **pre-commit hook 加敏感字段 grep 软警告**:
   ```bash
   STAGED_DIFF=$(git diff --cached -U0)
   SENSITIVE_HITS=$(echo "$STAGED_DIFF" | grep -E 'stageNames\s*=|Step.*of \d|of N\)|of \\\(total\\\)' || true)
   if [ -n "$SENSITIVE_HITS" ]; then
     echo "⚠️  敏感字段改动检测(向导结构 / footer 文本):"
     echo "$SENSITIVE_HITS"
     echo "请确认:这是 task md 派下来的改动?还是自发?自发改这类需 handoff 协调端"
     sleep 5
   fi
   ```

5. **Dev 端登记反模式触发条件之一**:commit 涉及敏感字段但无 task md → 强制走沉淀

## 判定线(Dev 视角)

- ✅ 自发修小 bug:fix: 颜色 / 间距 / 文案 / 单 hunk 状态修复 / 1-2 文件
- ❌ 自发修敏感:改 `stageNames` / Step 文本 / scaffold base class / Mock URL 批量 / ≥3 文件 = 必须 task md

## lint 状态

- Dev 工作流类,无静态扫描 → 子端 CLAUDE.md 自发修复边界段 + pre-commit 软警告
