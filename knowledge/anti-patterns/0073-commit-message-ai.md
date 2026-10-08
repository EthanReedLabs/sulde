---
doc_id: "ap-0073"
container: anti-patterns
platform: none
summary: "0073 commit message 写得像 AI 报告"
---

# 0073 commit message 写得像 AI 报告

- **平台**:双端
- **复发次数**:0

## ❌ 错误

```
feat: Phase 1 完成首页 UI 还原（Tab + 底栏 + 视频区 + 操作栏 + 字体）
fix: 经过分析修复 8 项 P0 偏差（Tab 下划线 + 按钮图标 + ProgressBar + ...）
refactor: 全量重构 Adapter 层，本次涉及 7 个文件
feat: ultrathink 思考后实现 5 阶段流程
feat: 批次 2 - Profile 全量对齐设计稿
```

## 为什么错（一眼看出 AI 痕迹）

- "Phase / 批次 / P0/P1" 真实工程师不会用;
- "经过分析"、"本次"、"全量" 是报告语;
- 括号里罗列 5+ 项是 AI 的总结习惯;
- "ultrathink"、"5 阶段流程" 直接暴露;
- 数量词("8 项"、"7 个文件")人类极少在 message 里写。

**会被客户代码审查 / git log 一眼识别为 AI 生成。**

## ✅ 正确（按 Dev 风格拟人化）

```
# 架构型，技术细节
feat: HomeFragment 用 ViewPager2 做竖滑
fix: ResultIntent 不能产生 Command
refactor: 抽个 AdaptiveBaseActivity

# 简洁型
feat: 某创作流参数页
fix: 模板瀑布流卡顿
style: 某面板间距调一下

# 基础设施型
feat: 接推送
fix: token 刷新偶发 401
chore: 升依赖版本
```

**判断标准**:写完 message 后自问"我是真人随手写的还是看起来像总结报告?"像报告就重写。

## 禁用词清单

- Phase / 阶段 / 批次 / Batch
- P0 / P1 / P2 / 优先级
- 全量 / 全部 / 完整版
- ultrathink / think hard / 5 阶段
- 经过分析 / 经过对比 / 本次 / 此次
- emoji(✅❌⚠️🔴🟡)
- 系统性 / 全面 / 深度
