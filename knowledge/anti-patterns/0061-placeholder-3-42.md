---
doc_id: "ap-0061"
container: anti-patterns
platform: none
summary: "0061 协调端凭印象不查技术真值"
---

# 0061 协调端凭印象不查技术真值

- **平台**:协调端(判断层) / 双端实施
- **复发次数**:7+

## ❌ 错误

协调端写 task md 时**凭记忆 / 习惯**判 framework / SDK / IDE 行为,不查官方真值。典型同模式多次复发:

- App Icon "单尺寸自动适配" 假设错(实际只对部分场景有效,设备主屏仍需多尺寸)
- SwiftUI `.offset(y:)` 影响 hit-testing 假设错(实际 visual-only,hit area 不随移动)
- iOS 16.x SwiftUI Image SVG `currentColor` + `.template` 渲染假设错(实际兼容性 bug,iOS 17+ 修复)
- 部署工具 "不 attach 调试器" 假设错(实际 attach 阶段已注入 hook → 老系统 trap)
- reducer body 凭 grep 2 行 context 推全局逻辑(未 Read 完整 body → 误报 bug)
- 双端 opacity 数值跨平台直抄(iOS 宽色域 + 浅 bg 视觉 OK,Android 窄色域 + dark bg 几乎吞没)
- 自定义 modifier / extension 凭命名假设行为(未 Read 定义 → 多轮 iteration 才修对)

→ Dev 严格按 task md 跑,跑完发现 framework 行为不符预期 → 回归。

## 为什么错

凭记忆判 framework 行为,不查:
- 官方开发者论坛(framework bug 报告 / beta release notes)
- 官方 HIG / 设计指南(图标标准 / 导航等)
- Stack Overflow(常见兼容性问题)
- WebSearch / WebFetch(实时真值)

grep 拿 2 行 context 推全局逻辑 ≠ Read 完整 reducer body;grep modifier 名 ≠ Read modifier body。

## ✅ 正确

1. 涉及 framework 行为 / API behavior / 已知坑 / 兼容性 → **必 WebFetch / WebSearch 实证**;
2. task md 引用证据 link(官方论坛 / Stack Overflow / HIG);
3. 涉及自定义 modifier / extension 时,task md 必含 modifier **真值贴片**(`grep -n "func {modifierName}"` 命中行号 + Read body 段),禁凭命名推断;
4. 涉及 reducer / setter / 初始化等完整逻辑维度,Read 完整 body 不只看 grep 行号;
5. 跨平台数值(opacity / color / spacing)不直抄,做双端视觉真值验证(色域 + dark theme 对比度差异)。

**判定线**:task md 涉及框架行为决策但**未引用官方真值 link**,或涉及自定义 modifier 但缺真值贴片 → 违规。

## lint 状态

- 难自动 lint(framework 行为 / 命名语义,grep 抓不住)→ 进协调端 task 起草 checklist:"涉及 framework 行为 / 自定义 modifier / 跨平台数值 → 查官方真值 + 贴 modifier body + 双端验证"。
- 派 Dev 时:默认模型不主动查真值,需查真值的任务必标高思考预算模型(opus 类)。

## 关联

- 本节是"协调端凭印象"父类反模式在**框架真值**维度的具体子集
- 0062(SVG `.template` 渲染 bug)/ 0063(`.offset` hit-testing)— 都是本节的具体技术案例
