---
doc_id: "ap-0041"
container: anti-patterns
platform: harmonyos
summary: "0041 协调端登记反模式后第一时间忘记应用 → 同源问题立刻复发"
---

# 0041 协调端登记反模式后第一时间忘记应用 → 同源问题立刻复发

- **平台**:协调端(工作流类) + HarmonyOS
- **复发次数**:2

## ❌ 错误(协调端工作流)

登记一条反模式当天稍后写下一个 task md,**第一时间就违反它**:

1. 在 audit-log / 反模式集合登记反模式 §X
2. 立即继续写新 task md,**忘记**让新 task md 符合 §X
3. 也不 sweep 已有 active task md 是否需 update
4. 结果:反模式登记的同时,**新违规 task md 同步产生** + **历史 active task md 仍违规** = 反模式仅是纸面规则,实施层零落地

**对称性**:**协调端自我反模式**(meta-anti-pattern)— 登记反模式仅是文档,**实施需要 sweep active tasks 验证全 fleet 符合**。

## 为什么错(根因)

- 反模式登记 = 文档行为(知识沉淀)
- 反模式应用 = 实施行为(每个新 task md 自检 + 已有 active sweep)
- 协调端容易把"登记 = 应用",实际两步分离,**应用环节必须显式触发**
- AI 协调端的"思维流"在写下一个 task 时不会自动召回最新登记的反模式 → 必须显式 sweep + checklist

## ✅ 正确(协调端工作流升级)

登记反模式 §X 后,**3 步必做**:

### 步骤 1:立即 sweep active task md

```bash
# 用 grep 检查所有 active task md 是否符合 §X 关键标志
for f in <平台>/.ai-workspace/tasks/*.md; do
  bn=$(basename "$f")
  png=$(grep -c "Read.*pen-truth.*\.png" "$f")
  attr=$(grep -c "关键属性 ≥ 3\|属性对照" "$f")
  audit=$(grep -c "非 pen-truth 元素自审" "$f")
  echo "$bn: Read png=$png 属性对照=$attr 非 pen-truth 自审=$audit"
done
```

输出 sweep 报告,标违规 task。

### 步骤 2:分类处理 active task

| task 状态 | 处理 |
|---|---|
| 已派但未跑 / 即将派 | **立即 update** task md 加 §X 强制要求 |
| 已派已跑过 | 加 **POST-HOC 警告头**(说明本 task 不符合 §X,如再做类似任务必须用升级版模板)|
| 已成功跑过 + 甲方验收通过 | 不动(避免破坏成功状态)|
| 已成功跑过 + 甲方验收发现差异 | 派**事后修复 task** 严格按 §X 写 |

### 步骤 3:协调端写新 task md 时必查 §X

每写新 task md 前,**自检 checklist**:本 task md 是否符合最近登记的反模式?

## lint 状态

- 协调端工作流类反模式,无静态扫描
- **预防 = 协调端 CLAUDE.md 加规则 + 每次登记反模式后必跑 sweep**

## 预防原则(给协调端)

1. 登记反模式 §X **必随附 sweep 命令**(grep 关键字检查 active task)
2. **登记后立即 sweep**,不能等下次 session
3. **写新 task md 前 checklist** 全部协作类反模式
4. **handoff 处理新反模式时同步**:任何新反模式登记后,grep audit-log 看历史 task / handoff 是否还有同源未消除

## UI 修改 preflight gate(同源变体:已沉淀规则未被应用)

同根因在 **UI/布局修复**场景的高频复发形态:一个"看起来只是小样式问题"的反馈进来,实施者直接读当前文件调参数,**跳过已沉淀的 UI 规则**(feature-parity / translate-rules / 相关反模式),于是重新踩已记录过的坑(如换行先缩字体、左偏先调 margin、`.w/.sp` 未同源缩放)。越像"顺手一改"的场景,越容易绕过 preflight。

**强制 gate**:任何 UI 修改 / 评审 UI handoff / 修 UI 问题**前**,先查沉淀源(feature-parity 规则 / translate-rules / 相关布局·浮层·锚点·键盘反模式),并**显式输出一句 preflight 结论**,写明命中哪条规则、风险点、本次意图范围:

```text
UI preflight: 命中 <规则>,风险点 <宽度/字号/锚点/浮层/资源/主题>,本次只改 <文件/层级>。
```

- 命中触发词(不对 / 换行 / 左偏 / 空白 / 弹窗 / 键盘 / 截图 / 平板 / 横竖屏 / 适配 任一)即进入 preflight,不许跳过。
- 缺少 `UI preflight:` 段的 UI 类修改 / handoff → **拒绝验收**,退回补 preflight。
- 修后回扣:说明命中规则如何对应到代码改动,并检查同类页面 / 同容器是否有同源模式。

## 典型适用场景(协调端任何反模式登记动作后)

- 反模式集合 / audit-log 登记新条目
- CLAUDE.md / UI 行为契约 加新强制规则
- pen-truth / page-relation 加新约束
- 任何"协调端规则升级"动作 → 必随 sweep + 自检
