---
name: bug-hunt
description: Bug 排查 / 找根因 / 复现问题 / 偶发 bug / 黑屏 / 卡死 / 数据不一致 / hunt bug / debug — 启动 3 人排查团队,从不同角度调查并讨论找根因(适合非崩溃类 bug)。当用户说"有个 bug""偶发问题""找下根因""为什么会出现""排查一下""页面卡住""数据不对"时自动触发。崩溃类用 /crash-fix。stack 中性 — 工具命令 / 排查维度从 references/{stack}.md 读。
user-invocable: true
---

# Bug 排查团队

启动一个 3 人排查团队,从不同角度调查问题,互相讨论找出最可能的原因。

**stack 决定后必先 Read 对应 references**:

| Frontend stack | 必 Read |
|---|---|
| `mobile-android` | `references/android.md` |
| `mobile-ios` | `references/ios.md` |
| `mobile-flutter` | `references/flutter.md` |
| `mobile-harmony` | `references/harmony.md` |

---

## §1 思考模式(强制)

**执行 `/bug-hunt` 时必须启用 ultrathink 深度思考模式。** Bug 排查易被表面症状误导,3 个 subagent 都用 ultrathink。

```
ultrathink。

3 阶段排查流程:

阶段 1【并行收集】
  - 主协调者并行调用:log 拉取 / git log / 读取相关源码 / Crashlytics
  - 不要串行收集,用 1M context 并行工具调用

阶段 2【3 角度分析】
  - 队友 1 / 2 / 3 各自从分配的方向独立分析
  - 每人输出:假设 / 证据 / 反证 / 置信度

阶段 3【交叉讨论 + 收敛】
  - 主协调者汇总 3 个假设
  - 找共同证据 + 矛盾点
  - 给出最终根因 + 修复方案 + 风险评估
```

---

## §2 启动方式

用户输入 `/bug-hunt` 后,依次问:

1. Bug 的具体表现是什么?
2. 复现条件和出现频率?
3. 在哪个分支上出现的?(默认 develop)
4. 有没有 crash log / 堆栈信息 / 错误日志?(可选)

---

## §3 执行步骤

1. **收集 Bug 信息**(表现 + 复现条件 + 分支 + 日志)
2. **根据 Bug 特征制定 3 个排查方向**(stack 特定常见维度见 references)
3. **创建 3 人团队**,每人负责一个方向 → 用 Agent 工具 spawn 子 agent,prompt 见 §5 模板
4. **队友之间互相讨论**,挑战对方的假设
5. **汇总结论**,给出最可能的根因和修复方案
6. **评估修复方案**是否会引入新问题、是否符合架构规则

---

## §4 队友分工维度

根据 Bug 特征动态分配排查方向。stack 通用维度:

- 生命周期 / 状态管理
- 内存 / 资源管理
- 线程 / 并发安全
- 网络 / 数据流
- UI 渲染 / 布局
- 平台兼容性 / 版本差异

stack 特定的常见排查切片见 references/{stack}.md §1。

---

## §5 队友 spawn prompt 模板

```
你是 {project} {stack} 项目的 Bug 排查工程师。

Bug 描述:{Bug 表现}
复现条件:{复现步骤}
出现频率:{频率}
所在分支:{分支名}
日志信息:{crash log / 堆栈 / 错误日志,如有}

你的排查方向是:{排查维度}

项目源码位置:当前工作目录(pwd)
请先 checkout 到 {分支名} 分支,再开始排查。

stack 特定工具:Read `${CLAUDE_PLUGIN_ROOT}/skills/dev/bug-hunt/references/{stack}.md` 拿 log 命令 / 调试工具 / 常见 pattern。

5 步排查:
1. 用 stack-specific log / Profiler / git log 收集证据
2. 列 3+ 假设,每个有反证 + 置信度
3. 找最近 14 天 commit 是否相关(git log -S "{symbol}")
4. 读关联代码(同模块 + 调用方 + 上游依赖)
5. 输出:假设 / 证据 / 反证 / 置信度 / 建议下一步

不修代码,只输出诊断报告。
```

---

## §6 汇总报告归档

写入 `.ai-workspace/diag/{date}-bug-{slug}.md`:

```markdown
# Bug 排查报告: {slug}

时间: {时间}
Bug 表现: {一句话描述}
复现条件: {步骤}
分支: {分支名}

## 3 队友诊断

### 队友 1: {维度}
- 假设: ...
- 证据: ...
- 反证: ...
- 置信度: 高/中/低

### 队友 2: ...
### 队友 3: ...

## 交叉收敛

- 共同证据: ...
- 矛盾点: ...
- 最终根因: ...

## 修复方案

- 方案: ...
- 风险: ...
- 验证步骤: ...
```

---

## §7 与 /crash-fix 的边界

- **crash-fix**:可拉到 crash log / 堆栈,有明确异常类型 → 用 /crash-fix(单 agent,4 阶段)
- **bug-hunt**:偶发 / 数据不一致 / 卡死 / 黑屏 / 无明确异常 → 用 /bug-hunt(3 agent 并行)

混合场景(有 crash 但根因复杂)先用 /crash-fix 抓 log,再切 /bug-hunt 多角度分析。

---

## §8 修复后必跑 /postmortem

bug 修完准备 commit 前**必先**跑 `/postmortem` skill 走 4 问漏斗(踩过吗 / 会再踩 / 能 lint 化 / 其他 frontend 也有),通过后才 commit。
