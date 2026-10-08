---
doc_id: "ap-0084"
container: anti-patterns
platform: none
summary: "协调端 task md 缺 UI 时序约束 → 双端动画 jank 对称返工"
---

# 0084 — 协调端 task md 缺 UI 时序约束 → 双端动画 jank 对称返工

- **平台**:双端通用
- **复发次数**:1

## 症状

双端按 task md 实现同一功能后，双端同时出现启动/关闭动画卡顿（jank）。症状完全对称，两端都严格按 task md 实现了指定的行为，没有任何平台实现错误。

## 根因

协调端 task md 行为契约只写了**数据约束**（读什么）+ **行为约束**（做什么）+ **结果约束**（产出什么），但漏掉第四类约束——**时序约束**（相对于哪个 UI 生命周期节点，何时做）。

执行端按 contract 实现，没有时序约束就无法判断"在进场动画期间执行是否合适"。两端各自的正确实现 × 同一个错误隐含假设 = 双端对称 jank。

**典型实例**:某列表缓存 task md 指定了"onAppear / onViewCreated 时从缓存读数据 + 渲染列表"，但未约束"必须在进场动画完成后"。Android Dev 在 `onViewCreated` 同步调用缓存预热，iOS Dev 在 reducer body（主 actor）同步调用缓存读取 + 设 state。两端都在进场动画期间（~300ms）绑定大量卡片 + 启动媒体播放器，主线程竞争导致动画卡顿。双端同时返工，分别写修复 task（Android: `lifecycleScope.launch { delay(300) }`;iOS: `.run { try? await Task.sleep(.milliseconds(300)) }`）。

## 判定线

task md 涉及以下任一 UI lifecycle 触发点，且缺少"时序约束"段 → 违规:

| 触发点 | 平台 |
|---|---|
| `onViewCreated` / `onCreate` | Android |
| `onAppear` | iOS SwiftUI |
| `viewDidLoad` / `viewDidAppear` | iOS UIKit |
| 构造注入时立即渲染 | 双端 |

## 修复：task md 必含"时序约束"段

```markdown
## 时序约束（涉及 onAppear/onViewCreated 必填）
- 触发点:onAppear / onViewCreated
- 动画状态:进场动画期间（约 300ms）禁止在主线程执行重渲染操作（N+ View 绑定 / 媒体播放器初始化）
- 执行时机:进场动画完成后
  - Android: `lifecycleScope.launch { delay(300); <操作> }`
  - iOS: `.run { try? await Task.sleep(for: .milliseconds(300)); <操作> }`
- 例外:用户主动触发（下拉刷新 / tap）无需 delay（用户已在页内，无转场动画）
```

## 协调端写 task md 自检

```bash
grep -E "时序约束|delay\(300\)|Task\.sleep|动画完成后|lifecycleScope.*delay" task.md
# 0 命中 + task 涉及 onAppear/onViewCreated + 有大批量渲染操作 = 违规
```

## 执行端识别信号（双端对称 = 协调端设计缺陷）

- 单端 jank → 平台实现 bug，自查
- **双端同症状、同功能、同时机** → 停止自查实现，协调端 task md 缺时序约束
- 正确 handoff:「双端都按 task md 在 onAppear/onViewCreated 触发渲染，但此时处于进场动画期间，建议协调端补时序约束」

## lint 状态

- 候选 lint:`rules/044-task-md-timing-constraint.sh`

## 关联

- task md 单维度行为契约（缺时序维度）
- task md 缺约束 → Dev 按直觉实现
- 协调端凭印象不查 UI lifecycle 时序真值
