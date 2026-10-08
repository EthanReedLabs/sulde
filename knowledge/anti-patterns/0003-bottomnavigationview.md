---
doc_id: "ap-0003"
container: anti-patterns
platform: android
summary: "用标准 BottomNavigationView 实现自定义形状底栏"
---

# 0003 — 用标准 BottomNavigationView 实现自定义形状底栏

- **平台**:Android

## ❌ 错误

拿系统的 BottomNavigationView 改样式硬凑设计稿的自定义形状底栏(如胶囊形 / 中央凸起按钮)。

## 为什么错

BottomNavigationView 内部布局逻辑固定,中央特殊按钮的特殊尺寸 / 选中态背景填充 / 非均分布局等做不到。

## ✅ 正确

自定义 LinearLayout 底栏,每个 Tab 独立配置尺寸与选中态。

**判断规则**:设计稿底栏含系统组件无法表达的结构(异形按钮 / 非均分 / 自定义选中态)→ 自绘容器,别硬改系统组件。

## lint 状态

- ❌ 难静态检查 → 人工 review / 设计对位 checklist。
