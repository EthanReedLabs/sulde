---
doc_id: "ap-0042"
container: anti-patterns
platform: none
summary: "0042 task md 留 fallback 口子 + 跨依赖糅合 → Dev 走 fallback 合规但违反用户…"
---

# 0042 task md 留 fallback 口子 + 跨依赖糅合 → Dev 走 fallback 合规但违反用户意图

- **平台**:协调端(task md 写作类)
- **复发次数**:1

## ❌ 错误(协调端 task md 留 fallback)

task md 某 stage 写"必须复用某共享组件;**如该端当前没有这个共享组件 → handoff 内声明 + 本任务先用占位 + TODO 不动结构**(防过度发散)":

```markdown
### Stage 2 — 复用某共享组件

#### 2.3 共享组件复用

- 必须复用某共享组件
- **如该端当前没有这个共享组件 → handoff 内显式声明 + 本任务先用占位 + TODO 不动结构**   ← ❌ fallback 口子
```

Dev 严格按 task md 跑 → 走 fallback 留 `// TODO: 待组件抽至公共层后复用` → **合规** → 甲方验收发现没复用 → 投诉。

⚠️ Dev 严格按 task md 跑会走 fallback,因为:
- fallback 工作量小(写 `// TODO`)
- 真做(抽组件)工作量大(超出 task 范围)
- fallback 是 task md 明文允许的合规路径
- = Dev 选 fallback 合理,但**用户意图(必须复用)未满足**

**对称性**:任何 task md 包含"如 X 不存在 → TODO / 占位"类 fallback 都可能踩。

## 为什么错(根因)

- 协调端写 task md 时为了"防过度发散",留了"如 X 不存在 → TODO"的 fallback
- 但 fallback 路径变成 Dev 的最低成本合规路径 → 必走
- task md 是 contract,Dev 严格 contract,**contract ≠ 用户意图**
- 协调端没自查"Dev 严格按 task md 跑会走哪条路径,fallback 会不会被走"

## ✅ 正确(协调端拆 2 task 串行,无 fallback)

```markdown
# Task 1(架构层)
## 抽某共享组件到公共层
- 本任务**就是**抽组件本身,无 fallback
- 完成 = 组件存在 + 既有调用方改用 + build 通过

# Task 2(应用层,Task 1 合主干后派)
## 真复用某共享组件
- 前置依赖:Task 1 已合
- 完成 = 调用方用共享组件 + 删 TODO 注释
- 不允许"占位"绕过(组件已存在,没 fallback 借口)
```

写 task md 时,**3 项硬约束**:

1. **task md 不留 "如 X 不存在 → TODO" fallback 口子**
   - 真做不到 → 协调端先派架构 / 前置 task,再派应用 task
   - 跨 task 依赖必拆 task,**串行派**(前置合主干后再派后续)

2. **写完 task md 自查"Dev 严格跑会走哪条路径"**
   - 模拟 Dev 严格按 task md 字面跑,看会不会有"Dev 选最低成本路径但违反用户意图"的可能
   - 发现 fallback 风险 → 删除 fallback 段或拆 task

3. **跨 task 依赖必拆**:
   - 不糅合"先抽组件后用组件"到一个 task
   - 不糅合"先抽 base class 后改子类"到一个 task
   - 不糅合"先建 lint 规则后清违规"到一个 task

## lint 状态

- 协调端 task md 写作类反模式,无静态扫描
- 预防 = 协调端 CLAUDE.md 加规则 + 写 task md 时自检 fallback 是否会被 Dev 走

## 典型适用场景(协调端写以下 task 时严控)

- 涉及"先抽组件 / 先建脚手架 / 先建 lint" + "再用 / 再清违规"两步的任务
- 涉及"如 X 已存在 → 用,如 X 不存在 → 占位"的条件分支
- 任何 task md 内含 "TODO" / "占位" / "暂时" / "fallback" 关键字 → 必须警觉是否变成 Dev 跳过实施的口子
