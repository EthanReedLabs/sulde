---
name: code-review
description: 代码审查 / Code Review / CR / 审一下分支 / 检查改动 / 合并前审查 / 评估代码质量 / review branch — 启动 2 人审查团队(架构合规 + 代码质量)审查指定分支相对 develop 的所有改动。当用户说"审一下 dev/xxx""code review""看下这个分支""合并前先审""check 一下代码质量"时自动触发。stack 中性 — 习语 / lint 工具 / 架构契约从 references/{stack}.md 读。
user-invocable: true
---

# 代码审查团队

启动一个 2 人审查团队,分别从架构合规和代码质量两个维度审查指定分支。

**stack 决定后必先 Read 对应 references**:

| Frontend stack | 必 Read |
|---|---|
| `mobile-android` | `references/android.md` |
| `mobile-ios` | `references/ios.md` |
| `mobile-flutter` | `references/flutter.md` |
| `mobile-harmony` | `references/harmony.md` |

---

## §1 思考模式(强制)

**执行 `/code-review` 时必须启用 think hard 思考模式。** 代码审查需要细致分析,但不需要 ultrathink 那么重。两个 subagent 各用 think hard。

```
think hard。

4 阶段审查流程:

阶段 1【并行加载改动】
  - `git diff develop...{分支} --stat` 获取改动文件列表
  - 并行 Read 所有改动的文件(利用 1M context 一次性加载)
  - 同时 Read 关联的依赖文件(Store + Adapter + Spec / Reducer + Feature 等)

阶段 2【按维度审查】
  - 队友 1:架构合规(模块依赖 / state machine 约束 / git 身份)
  - 队友 2:代码质量(内存 / 并发 / 错误处理 / 性能)
  - 各自输出问题清单 + 严重程度(阻断 / 需修复 / 建议)

阶段 3【交叉验证】
  - 互相检查对方遗漏的点
  - 重复问题去重

阶段 4【写报告】
  - 写入 `.ai-workspace/reviews/{分支}-{日期}.md`
  - 不修改代码,只输出报告
```

---

## §2 启动方式

```
/code-review {branch-name}
```

或交互式:用户输入 `/code-review` 后,问"审查哪个分支?"。

---

## §3 执行步骤

1. **确认分支名**
2. **抓 diff**:`git diff develop...{branch} --stat` + `--name-only`
3. **并行 Read** 全部改动文件 + 关联上下文(Store / Reducer / Repository / 等)
4. **spawn 2 人审查团队** via Agent 工具:
   - 队友 1:架构合规
   - 队友 2:代码质量 + 性能
5. **汇总报告**:`.ai-workspace/reviews/{branch}-{date}.md`
6. **不修改代码**(本 skill 只审查,修复另派 task)

---

## §4 队友分工

### 队友 1:架构合规审查

通用维度(stack 通用):
- **state machine 约束**:state transition / reducer pure / side effect 隔离(stack 特定见 references §1)
- **模块依赖方向**:Feature 不依赖其他 Feature,只依赖 Spec / Port / core-ui
- **分支 → 作者 alias** 一致性(commit author 与 `.sulde-config.yaml: team[]` mapping 匹配)
- **AI 痕迹**:代码中无 `AI / Claude / GPT / LLM / generated / auto-generated`
- **非源码文件未泄漏**:`.ai-workspace/` 类文件不应在源码目录
- **commit message 拟人化**:无 Phase / 批次 / P0 / emoji / 数字罗列

stack 特定架构契约见 references/{stack}.md §1。

### 队友 2:代码质量 + 性能审查

通用维度:
- **内存管理**:未释放的资源 / 引用泄漏 / 监听器未注销
- **并发安全**:async 边界 / 主线程违规 / 状态可见性
- **错误处理**:统一错误类型 / 未处理 error 分支 / silent error
- **资源清理**:页面退出时 release / 监听器在合适位置 cancel
- **重试策略**:可重试错误用指数退避(2/4/8s)
- **null safety / Optional**:强解 / 隐式假设
- **性能反模式**:同步 IO 在主线程 / 大列表无 diff / 大图无压缩

stack 特定常见反模式 + lint 命令见 references/{stack}.md §2-§3。

---

## §5 spawn prompt 模板

```
你是 {project} {stack} 项目的代码审查员,角色 = {合规 | 质量}。

待审查分支:{branch-name}
diff:`git diff develop...{branch} --name-only`(已并行 Read 全部文件)

项目源码位置:当前工作目录(pwd)
模块依赖:见 `<docs-hub>/00_shared-rules/data-sources.md` + `<docs-hub>/编码原则集.md`

你的审查维度:{合规 | 质量}
stack-specific 检查表:Read `${CLAUDE_PLUGIN_ROOT}/skills/dev/code-review/references/{stack}.md` §{1|2}

4 阶段:
1. 并行加载 + 关联依赖 Read
2. 按维度逐文件审,每发现问题输出 `file:line | 严重程度 | 描述 | 建议`
3. 自我交叉验证(漏点排查)
4. 输出报告段(不修代码)

严重程度:
- 🔴 阻断 — merge 前必修(架构违规 / 数据丢失风险 / crash 风险)
- 🟡 需修复 — merge 前修(可读性差 / 性能差 / 错误处理缺)
- 🟢 建议 — 可后续 PR 优化
```

---

## §6 审查报告格式

`.ai-workspace/reviews/{branch}-{date}.md`:

```markdown
# Code Review: {branch}

时间: {date}
diff: `git diff develop...{branch} --stat`
改动文件: {N} files / +{ins} -{del}

## 队友 1 - 架构合规

### 🔴 阻断
| file:line | 描述 | 建议 |
|---|---|---|
| ... | ... | ... |

### 🟡 需修复
...

### 🟢 建议
...

## 队友 2 - 代码质量

(同结构)

## 总结

- 阻断: {N} 项 → 必修后才能 merge
- 需修复: {N} 项 → merge 前处理
- 建议: {N} 项 → 后续 PR

下一步: {继续修 | 阻断需用户拍板 | 可 merge}
```

---

## §7 与 /assign / /postmortem 的关系

- `/code-review` 只产出**报告**,不修代码
- 报告里的 🔴 / 🟡 项 → 由协调端写 fix task md,用 /assign 跑(详 writing-task-md SKILL)
- 修完任 fix 后,**bug 类问题必跑 /postmortem 4 问漏斗**,登记 ADR / 加 lint rule
