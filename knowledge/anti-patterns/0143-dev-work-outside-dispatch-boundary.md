---
doc_id: "ap-0143"
container: anti-patterns
platform: none
summary: "Dev 主任务 ship 后自驱 polish bundle 绕过协调端 task md 边界"
---

# 0143 — Dev 主任务 ship 后自驱 polish bundle 绕过协调端 task md 边界

- **平台**:协调端方法论
- **复发次数**:1
- **lint 状态**:⏳ pending(handoff / branch 两道 hook 已就绪,Dev 端 settings 挂载后 enforce)

## 现象

Dev session 跑完某 task md 的主任务、**协调端 review 前**,又**自创一条新 branch**(无对应 task md)+ 跑一大批 polish commit + 写一份独立 handoff → 整包绕过协调端 task md 派单体系。

典型实证:主任务 ship 后,Dev 从主任务末尾 fork 一条自命名 branch,顺手跑几十个 commit 的"跟真值 1:1 大 sweep",再单独写一份 `-result.md` handoff 交上来 —— **没有任何协调端 task md 对应**,协调端 review 时看到 outcome ✅ 就顺手 accept,process 维度失守。

要与其区分的**合法直修场景**(见下 ✅):甲方真机反馈触发的 fix、已知根因 bugfix、协调端无真机能力时的 spike/真机 verify —— 这三类 Dev 可直接修,不必回协调端起 task md。

## 为什么

| # | 真因 |
|:-:|---|
| 1 | 甲方临时反馈直接打到 Dev 终端;跨终端 process 不严格 + 甲方同开多终端的习惯,反馈没经协调端漏斗 |
| 2 | Dev 收到反馈后没"refuse + 转协调端",而是自主开跑;Dev 端规则禁了"自己派任务给别 Dev",但"self-drive 自己给自己派活"不在禁清单里 |
| 3 | 无 hook 拦 branch 名 / handoff 的 Task path 合规;模板层是软约束,可绕过 |
| 4 | 协调端 review 只看 outcome ✅ 即 accept,缺 process 维度审计(有没有对应 task md)|

**范围要narrow**:早期把"Dev 无反馈自驱 polish drift"和"甲方真机反馈触发 fix"混为一谈,导致连甲方反馈也强制走协调端 task md → 反馈循环拉到数小时,而协调端在无真机 ground truth 下起草的实现草稿编译/视觉双错 → ROI 反向。核心反模式只应命中**无外部反馈的自驱 polish**,不误伤真机反馈直修。

## ✅ 正确

**默认漏斗**:甲方反馈 → 协调端 → task md → Dev 派单 → Dev 实施 → handoff → 协调端 review → ff-merge。

**三类合法直修豁免**(Dev 可跳 task md,但 branch 名与 handoff 必带对应前缀 / 后缀标识):

| 场景 | 协议 |
|---|---|
| 甲方真机反馈直接给 Dev + Dev fix | ✅ Dev 直接修;handoff / branch 带 `userfix-` 标识 |
| 已知根因 bugfix | ✅ Dev 直接;带 `bugfix-` 标识 |
| spike / 平台 API 真机 verify(协调端无真机能力)| ✅ Dev 直接;带 `spike-` 标识 |
| 大型 reimpl / 跨端 / 架构决策 | ❌ 必走协调端 task md |

**仍禁**:

- ❌ 主任务 ship 后**无任何外部反馈**,自创 branch 跑 polish bundle(本反模式核心)
- ❌ 自命名 branch 无 `userfix-` / `bugfix-` / `spike-` 前缀 + 无对应 task md
- ❌ `userfix` branch 顺手扩 scope 干其他 polish(如"改状态栏色"顺手 fix 别处组件)

**协调端 review 补 process 维度**:review handoff 时除 outcome,必核"有无对应 task md / 是否合法豁免前缀",防偷偷 ship。

## lint 状态

⏳ pending —— 两道 hook 已就绪,Dev 端配置挂载后 enforce:

1. **handoff Task path 拦截**:写 handoff `-result.md` 时必含 Task path 且对应 task md 必存在,否则拒 Write;`userfix|bugfix|spike` 后缀豁免。
2. **branch 名 vs task md 匹配**:自命名 branch 必有对应 task md,否则拒 push;`userfix-|bugfix-|spike-` 前缀豁免。

- 关联:某反模式(协调端禁 sub-agent 自行实施,sibling:Dev 亦禁绕协调端 self-drive);某反模式(Dev 单 session 一次跑通 —— 本条是其边界:single-session 主任务 OK,但 self-drive 起新任务禁)。
