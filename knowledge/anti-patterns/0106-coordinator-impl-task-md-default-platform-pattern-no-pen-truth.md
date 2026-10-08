---
doc_id: "ap-0106"
container: anti-patterns
platform: none
summary: "协调端实装 task md 凭\"通用平台模式\"决定播放/弹窗/导航形态不查 pen-truth"
---

# 0106 — 协调端实装 task md 凭"通用平台模式"决定播放/弹窗/导航形态不查 pen-truth

- **平台**:协调端
- **复发次数**:0(归因到"凭印象不查实证"同源根因)

## ❌ 错误

协调端写"实装 / 视觉 / 导航形态"类 task md 时,凭 "iOS 通用 UX 模式"(fullScreenCover / sheet / push / NavigationStack)或 "Android Material 模式"(Dialog / BottomSheet / startActivity)直接决定播放/弹窗/导航形态,**不 quote pen-truth `{pageId}.md` nodeId 真值**也**不 escalate user 拍板**。

真值:user 期望可能与"通用平台模式"完全不同(如 "在当前页内播放视频" vs "弹全屏播放器"),pen-truth 视觉契约才是真值;凭印象设计 = task md 起草后必被 user 真机推翻 → Dev 多 round 返工。

```
协调端写实装 task md(某播放交互)
↓
凭 "fullScreenCover 是视频播放标准 UX 模式" 直接写全屏播放器
↓
没 quote pen-truth nodeId 真值,没 escalate user 拍板 "当前页 vs 弹全屏"
↓
Dev 跑 v1 → user 真机推翻 "在当前页面播放不是拉新页"
↓
Dev 改就地播放(@State AVPlayer + 页内 VideoPlayer)
```

## 为什么错

**协调端实装 task md 起草前缺 "pen-truth nodeId 真值 quote OR escalate user 拍板" 硬约束**:

- 协调端有能力用设计稿工具 batch_get 节点真值 + Read pen-truth line N,但没硬约束起草前必 quote。
- 凭 "通用 UX 模式" 等抽象原则代替 pen-truth 真值。
- 实装 task md 决定**播放 / 弹窗 / 导航 / Modal / Toast / Dialog 形态**时 pen-truth 才是真值,凭"通用模式" = 凭印象设计。

## ✅ 正确

```
协调端写实装 task md 前
↓
Read pen-truth {pageId}.md + .png + 设计稿工具 batch_get
  → 找目标交互节点真值
↓
若 pen-truth 含 "页内 VideoPlayer 区块" → quote line N
若 pen-truth 缺该节点 → task md 顶部加:
  "## escalate user 拍板
   - 选项 1:当前页内 VideoPlayer
   - 选项 2:弹全屏播放器
   - 等 user 决策再签发实装方向"
↓
不签发"通用平台模式"默认形态
```

机制层强制内容:

| 强制内容 |
|---|
| 实装 / 视觉 / 导航类 task md 起草前**必 quote pen-truth `{pageId}.md` 真值 nodeId 或 line N** |
| 涉及决策项:fullScreenCover / push / sheet / 就地播放 / Modal / Toast / Dialog / BottomSheet / NavigationStack / startActivity 等 |
| 若 pen-truth 缺该交互节点 → **escalate user 拍板**,不签发实装方向 |
| **不允许凭 "通用 UX 模式" / "Material 模式" 决定形态**;双端同款 |

## lint 状态

- ⏳ pending(协调端判断类)→ 进 task md 起草 checklist。

## 协调端自检(实装/视觉/导航类 task md 起草前)

- [ ] task md 涉及 fullScreenCover / push / sheet / 就地播放 / Modal / Toast / Dialog / BottomSheet 形态决策?
- [ ] Read pen-truth `{pageId}.md` + .png 了?设计稿工具 batch_get nodeId 真值?
- [ ] task md "视觉契约 / 导航形态"段 quote pen-truth line N 或 nodeId?
- [ ] 若 pen-truth 缺该节点 → task md 顶部加 "escalate user 拍板"段?
- [ ] 双端同款检查?

任一 ❌ = 不签发 task md,补 pen-truth quote / escalate 再起草。

## 关联

- 协调端起草前未跑 baseline(本款是其在实装/视觉/导航形态路径的子模式)。
- 与"task md 引过时 pen-truth"互补:那是 quote 了 stale,本款是根本没 quote。
- UI task 必导 .png 不凭文字猜(本款扩展到"导航/交互形态")。
