---
doc_id: "ap-0034"
container: anti-patterns
platform: none
summary: "任务书硬约束写字面行数而非意图"
---

# 0034 — 任务书硬约束写字面行数而非意图

- **平台**:协调端 task md 写作
- **复发次数**:0
- **lint 状态**:无法静态 lint，协调端任务书写作规范

## ❌ 错误

协调端任务书硬约束写 "只加 1 行 listener 注册"（字面量）。

## ✅ 正确

写意图 — "不动 Dev B 领域代码（ViewHolder 类型 / feed 逻辑 / Banner / 分页）"。

## 为什么错

- Dev 按平台官方推荐的回调注入模式做（Adapter 加回调接口 + Fragment 加 menu 方法 = 架构更干净）
- 若强行按字面"1 行 listener 塞 VH"，VH 需持 FragmentManager（生命周期危险）或反射找 context（hack）
- 意图已达成（未动其他 Dev 领域），字面约束是过度精细化

## lint 状态

- ❌ 无法静态 lint
- 协调端给终端写指令时硬约束写意图，不写字面行数

## 关联

- 反模式 0037 / 0038（同源协调端任务书规格不严）
