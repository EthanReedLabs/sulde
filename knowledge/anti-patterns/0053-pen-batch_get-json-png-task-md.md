---
doc_id: "ap-0053"
container: anti-patterns
platform: none
summary: "0053 协调端读 .pen batch_get 拿 JSON 节点数据但不导 .png 视觉对照 → 凭文字描述猜形…"
---

# 0053 协调端读 .pen batch_get 拿 JSON 节点数据但不导 .png 视觉对照 → 凭文字描述猜形态 → 双端 task md 反复误派

- **平台**:协调端(UI task 写作类)
- **复发次数**:1(同日 3 次误派)

## ❌ 错误 — 症状

协调端用 Pencil MCP `batch_get` 拿到 .pen 的节点 JSON(width/height/fill/stroke/cornerRadius 字段齐全),但**不调** `mcp__pencil__export_nodes` 导出 .png 视觉验证。仅凭节点 JSON 的字段值文字推断 UI 形态,**形态判断高频出错**:

- 节点 width=402 / height=874 → 误判"全屏页"(实际可能是带 dimmer 的 modal,内层弹窗 width 370)
- 节点 cornerRadius:20 → 误判"圆角卡"(实际可能是浮层圆角 + 外层 dimmer 半透明)
- 节点没有 dimmer 显式标注 → 误判"无 dimmer"(实际外层 dimmer 是单独 sibling frame opacity 0.76,不是子元素)

## 为什么错(根因)

某 picker 页实例:
- 用户报"新版 UI 是弹窗形式" → 协调端 grep .pen 看到 frame 是 402×874 → 误判"全屏页非弹窗"
- 用户提示"路径一致,跳转是二级页面不是弹窗" → 协调端误读,派 iOS 把 `.fullScreenCover` 改 `.navigationDestination` push(已合主干后回滚)
- 用户进一步反问 → 协调端再误判,派 Android 改 BottomSheet 全屏 `MATCH_PARENT`
- 用户最终问"是不是缺对照图" → 协调端**才**用 `export_nodes` 导出 .png:看到真值是**居中圆角 sheet + dimmer 0.76**(width 370 内层弹窗 + 外层 dimmer sibling frame),双端实现都错

→ **同一天 3 次误派的根因都是同一个**:有节点 JSON 但缺视觉对照,凭字段值文字推断形态

## ✅ 正确 — 修法

协调端用 Pencil MCP 处理任何 UI 任务前**必跑 2 步**(单步缺一即不合格):

1. **batch_get 拿节点树**(readDepth ≥ 5 + 含 image / icon_font patterns)
2. **export_nodes 导 .png**(scale: 2,outputDir 到 pen-truth/ 目录)
3. **Read 导出的 .png**(协调端用 multimodal 视觉验证形态 — modal vs page / dimmer 有无 / 圆角位置 / 内外层关系)
4. **生成 pen-truth/{pageId}.md**(节点属性对照表 + 视觉资源清单 + **形态语义段**:明确说"这是 modal/page/dialog/popover")

## 判定线

协调端 task md 派单前 grep 自检:

```bash
ls "pen-truth/{pageId}.png"   # 必有
ls "pen-truth/{pageId}.md"    # 必有
grep "形态语义\|modal\|page\|popover" pen-truth/{pageId}.md   # 必命中
```

3 项任一缺失 = 违规,task md 不合格。

## lint 状态

- Android/iOS:N/A(协调端职责)
- 协调端:⏳ TODO(`scripts/lint-task-md.sh` 加 grep `pen-truth/.+\.png` 必含 + `形态语义` 段必含)

## 关联

- 协调端凭印象 — 凭印象 = 双重违规
- 单维度数据源 — 本条是其在 UI 维度的具体子集(只看 .pen 节点 JSON 是单维度)
- shared-rules `data-sources.md`(`pen-truth/{pageId}.md + .png` 双产物必备)
