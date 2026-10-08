---
doc_id: "ap-0054"
container: anti-patterns
platform: none
summary: "0054 协调端 task md 给完整代码 boilerplate + 标 model: sonnet → Dev…"
---

# 0054 协调端 task md 给完整代码 boilerplate + 标 model: sonnet → Dev 退化翻译机 / 不抽抽象 / 不思考复用

- **平台**:协调端(task md 写作类) + Dev
- **复发次数**:2

## ❌ 错误 — 症状

协调端写 task md 时给 Dev 完整代码骨架(完整 Kotlin / Swift 类 + XML / SwiftUI body 内容 + drawable / styles 配置),Dev 拿到只能 copy-paste。**Dev 失去抽象判断机会**:

- 同一视觉模式跨 picker / 跨页面重复**实现 ≥ 2 次**,每次都重写,**不抽公共控件**
- 跨页常见模式(圆角 image / gradient stroke 卡 / 居中圆角 sheet 容器 / Material Button inset 清零)在 ≥ 3 个 task 中重复出现,从未抽到 `core-ui/widgets/`
- Dev handoff "为什么改这些"段不写"我是不是该抽控件",反映 Dev 没在思考层面运转 — 只在执行层运转
- 多 picker 共享形态由协调端在每个 task md 重新写一遍,Dev 跟着每个 task md 抄一遍

## 为什么错(深层因果链)

```
task md 给完整代码 boilerplate
  → Dev 标准 sonnet 模型只走 instruction-following
  → Dev 看 task md 像 "翻译规格说明书"
  → 不停下来问 "这是不是 pattern" / "上次是不是写过类似" / "能不能抽出来"
  → 跨 picker 重复实现同样代码
  → 重复代码积累 + 没有抽象 = 改一次要改 N 处 + 还原度低
```

## ✅ 正确 — 修法(协调端 + Dev 两端责任)

### 协调端 task md 风格切换:contract-based,不给 boilerplate

**旧模式**(禁):
```kotlin
// task md 写完整代码骨架
class StylePickerBottomSheet : BaseBottomSheetDialogFragment() {
    override fun onStart() {
        super.onStart()
        // 50 行 BottomSheet 配置...
    }
}
```

**新模式**(强制):
```markdown
## 视觉契约
弹窗形态:居中圆角 sheet,370 wide,顶部留 56,圆角 20,dimmer 0.76,slide-in-bottom

## 复用思考(强制段 — Dev 必填)
- core-ui 是否已有相似控件?有 → 继承复用;无 → **本 task 顺手抽 + 后续 picker 复用**
- 当前改的视觉模式(圆角 image / gradient stroke / 居中弹窗 / button inset)是不是已经在其他页/其他 picker 出现?是 → 抽 core-ui/widgets/ 公共控件
- handoff 必填"抽了哪些公共控件 + 哪些场景能复用"

## 数据契约
入参 / 出参 result key

## 反模式禁区
- 不要直接抄 BottomSheetDialogFragment 配置(此容器先天底部对齐,不能精确居中)
- 不要用普通 ImageView(图片不跟随父圆角)
- 不要用 layer-list selector 做 stroke + fill(双层 radius 不一致 → 边角断裂)
```

contract-based,Dev 看到必须**主动思考**才能写出代码。

### model 选择:涉及抽象 / 复用决策 → opus

任务 frontmatter `model:` 字段,涉及"抽象 / 复用 / 举一反三"决策时**必标 opus**:
- 抽公共控件 / base class / scaffold 升级
- 跨页 / 跨 Feature 共享视觉模式
- 多页面规律识别 + 抽象判断

## 判定线

协调端 task md 自检:

```bash
# 检查 task md 是否给 boilerplate(超过 30 行连续代码块 = 风险)
grep -c '^```' .ai-workspace/tasks/{file}.md
# 块数 ≥ 6 = 可能给完整骨架,违规

# 检查是否含"复用思考"强制段
grep -E "复用思考|公共控件|抽 .*core-ui|core-ui/widgets" .ai-workspace/tasks/{file}.md
# 0 命中 = 违规
```

任一项失败 = task md 不合格,协调端必须重写为 contract-based。

## Android 特化清单(本反模式高发场景,Android UI XML 必抽公共控件)

| 视觉模式 | 必抽控件 | 路径 |
|---|---|---|
| 圆角图片 + centerCrop | `RoundedImageView`(扩展 ShapeableImageView)| `core-ui/widgets/image/` |
| 卡片选中态 gradient stroke + 圆角 | `GradientStrokeFrame`(自定义 FrameLayout 重写 dispatchDraw)| `core-ui/widgets/card/` |
| 居中圆角 sheet 容器 + dimmer + slide-in | `AppCenterSheetDialogFragment`(基类)| `core-ui/widgets/dialog/` |
| Material Button inset 清零 | 不需抽控件,XML 模板硬约束 `app:insetTop="0dp"` | values/styles.xml 默认 style |
| RecyclerView item inline expansion 视觉合并 | 卡片 + overlay 必须 **margin=0 紧贴 + cornerRadius 合并(顶+底分别圆角)+ 共享 stroke**;不能简单"在 item 下方塞 view" | drawable XML 拆顶/底圆角 + Adapter VH 切 drawable |

任何 Android UI 还原 task md **必含本表对照**。

## 双端 UI 实现路径差异预案(基于平台规范,不参考另一端)

**核心认知**:协调端基于平台规范(Apple HIG / Android Material Design)给双端各自标准路径,任何一端 Dev 实施都不依赖另一端先完成。

**视觉 vs 实现路径分离原则**:

| 维度 | 双端关系 | 来源 |
|---|---|---|
| **视觉契约**(尺寸 / 圆角 / fill / stroke / lucide 图标) | **必双端一致** | 对齐 pen-truth(设计稿真值) |
| **实现路径**(用什么 API / 容器 / 渲染策略) | **不强制一致**,各端按本平台规范选最自然写法 | iOS Apple HIG + SwiftUI WWDC 推荐;Android Material Design + Jetpack 推荐 |
| **行为契约**(交互 / 状态切换 / 数据回传) | **必双端一致** | PRD |

协调端 task md 写 UI 实现时,必显式给双端"基于平台规范的实现路径":

| 场景 | iOS 实现路径(Apple HIG / SwiftUI 标准)| Android 实现路径(Material Design / Jetpack 标准) |
|---|---|---|
| 列表内 inline expansion | List/ForEach 内插入展开内容作为选中 row 视觉延续(`if let { ExpandedView }` 紧贴);或 `DisclosureGroup` | RecyclerView 单 ViewType + ViewHolder 内嵌 expanded section,bind 切 drawable(顶/底圆角拆)+ margin=0 + 共享 stroke;**禁** "卡片下方加独立 view 切 visibility"(视觉=2 个独立 item)|
| modal / 浮层 | `.sheet` / `.fullScreenCover` / 自画 ZStack overlay | BottomSheetDialogFragment / DialogFragment / PopupWindow / inline view |
| 圆角图片 | `Image().clipShape(RoundedRectangle)` GPU mask | `ShapeableImageView` / Coil RoundedCornersTransformation;**禁普通 `<ImageView>` + 父圆角 drawable** |
| 渐变 stroke | `.overlay(RoundedRectangle.stroke(LinearGradient(...), lineWidth:N))` | 自定义 FrameLayout 重写 dispatchDraw 用 `LinearGradient Shader + Path.stroke`;禁 drawable `<stroke gradient>` |

**Why 必须协调端显式给路径**:仅描述视觉效果(让 Dev 自由发挥),双端 Dev 各自选实现。某端 Dev 选错 → 视觉分离 / 形态偏差。**这不是 Dev 能力问题,是 task md 缺路径决策的根因**。"一端一次 OK / 另一端 60-70% 还原度" 90% 概率根因 = task md 模糊 / 没显式实现路径 + 视觉合并约束。

**判定线**:协调端写涉及列表 inline / 浮层 / 圆角 / 渐变 stroke 的 UI task md,必含 "**双端实现路径**" 显式段。

## lint 状态

- Android/iOS:Dev mini-checklist 加"我是不是在重写第 N 次相同模式?是 → STOP 抽控件再继续"
- 协调端:⏳ TODO(`scripts/lint-task-md.sh` 加 grep "复用思考" 段必含 + 代码块数检查)

## 关联

- task md 留 fallback — 同属"task md 写法反模式",本条是"给太多 boilerplate"
- 协调端凭印象 — 不凭印象但**凭 boilerplate 抄而不思考**
- 模型选择 — model 标错(sonnet 跑抽象决策)= 双重违规
