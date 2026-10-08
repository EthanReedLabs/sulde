---
doc_id: "ap-0124"
container: anti-patterns
platform: cross
summary: "0124 adapter wrap ≠ 真链路 — 验链路必查文档 + 消费方 + live 正向验证"
---

# 0124 adapter wrap ≠ 真链路 — 验链路必查文档 + 消费方 + live 正向验证

- **平台**:协调端 / Android / iOS / 后端文档
- **复发次数**:1

## ❌ 错误

协调端凭**单一证据**反推真链路:看到 "adapter 已 wrap + grep Feature 0 调用者" 就推断"这是真链路 / Feature 层漏接",或凭 adapter wrap + DI 绑反推"应该调它"。

实际两类失误:
- **wrap 本身就错向**:被 wrap 的 endpoint 属于另一产品线 / 另一场景,根本不该用于目标链路。
- **wrap 已建但闲置**:Adapter 层早已 wrap(桥接 endpoint → interface),但 Feature 层从没调 → 死代码,真正需要它的流程走了 fallback(如最终视频无音轨)。

```bash
# Feature 层调用者:
grep -rn "pollVmStatus" feature-create feature-home Sources/Feature*
# 命中 0

# Adapter 层:
grep -rn "pollVmStatus" .../adapter Sources/AdapterAI
# 命中 ✓(建了但没人调)
```

## 为什么错

- **Adapter 层抽象 = "桥接"**(endpoint → interface),**不等于"被使用"**(Feature 层调用)。
- 协调端沉淀真值时只看"endpoint 是否在文档定义"+"Adapter 是否 wrap",不查"Feature 是否真用",也不 verify "wrap 的 endpoint 本身是否归属本场景"。
- 多次走错轨,都因"单一证据反推"。

## ✅ 正确

验链路有效性**禁凭单一证据**,四管齐下:

| Step | 必做 |
|:-:|---|
| 1 | **通读接口文档目标场景的数据章节**(不只 endpoint 列表,看上下文章节标题 + 场景定位)|
| 2 | **查 UI / Feature 层真热路径**(grep symbol 在 Feature 层命中数 + 实际 caller 链路)|
| 3 | **live 正向验证**(真机 curl / 抓包跑一遍 endpoint,看实际响应是否合预期 schema + 业务字段)|
| 4 | **adapter wrap 仅作"已建提示",不作真链路证据**(wrap 存在 ≠ 该 endpoint 是本场景真链路,可能 wrap 本身就错向)|

任一 Step 缺 → 反模式触发,task md / 真值沉淀拒签发。

补充:
- 协调端沉淀 endpoint 真值时必跑 4 步 audit(文档定义 → Adapter wrap → interface → Feature 调用),若 Feature 0 调用 → 标 ⚠️ 闲置 wrap,真值复用不重建。
- Spec / Adapter 的 interface 必含"调用场景 + 调用顺序"docstring,防"建了没调"。
- audit 优先级:既有真机日志 > Adapter wrap 反向 grep + Feature grep > 真包对照文档 > 抓包(最后)。

## lint 状态

⏳ pending — 脚本化:查 Adapter 内 wrap 的 endpoint 是否有 Feature 层调用者;若 wrap 已存 ≥1 月 + Feature 0 调用 → 软警告"可能死代码闲置"。

## 关联

- 协调端漏读文档新版(同源)
- endpoint vs 场景错位(同源)
- 凭印象不查实证(同源)
- "验链路禁凭 adapter wrap 反推真链路"经验(必通读文档场景章节 + 查 UI 消费方 + live 正向验证三管齐下)
