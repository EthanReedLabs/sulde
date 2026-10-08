---
doc_id: "work-model/cross-stack-parity-loop"
container: work-model
platform: none
summary: "**项目无关工作模型。"
---

# 跨栈对齐修复 SOP:源真值端 → 目标端 parity loop(canonical)

> **项目无关工作模型。** 适用于**任何「目标端实现与源真值端不一致 / 视觉 / 交互细节」类修复**。
> 下文以 **Flutter(源真值端)⇄ HarmonyOS/ArkUI(目标端)** 作为一对 generic「源栈 → 目标栈」的**跑例**;换成任意别的 pairing(如 Web→原生、iOS→Android、旧栈→新栈)回路不变,只换工具命令。
> 一手真值 = **连着的源真值端 stack 在真机上的实际行为**(不是 design-truth 二手提炼、不是印象、不是现有 WIP)。
> 核心回路一句话:**反抽源真值 → 转译到目标端 → 真机 runtime 验收 parity → 差异沉淀成反模式/知识库**。

---

## 0. 设备变量(重连换 ID 即可)

每对源→目标 pairing 各连一台真机,变量化设备序列号:

```bash
source <目标端 SDK 环境脚本>          # 每个新 shell 必跑(目标端工具链 PATH)
TDEV=<目标端设备列举命令的序列号>      # 目标端 stack 被测端(如 HarmonyOS: hdc list targets)
SDEV=<源端设备列举命令的序列号>        # 源真值端 stack 一手真值端(如 Flutter/Android: adb devices)
```

**分辨率 / density 对齐**:记录两机的像素分辨率与 dp 换算(如 480 density → 360dp 宽)。两机分辨率相近时坐标基本通用,但仍各自用**本端设备列举命令**核对当前序列号,勿硬拷旧 ID。

**canvas 渲染栈的导航铁律**:若源真值端是 canvas 渲染(如 Flutter),控件树 dump **拿不到节点**(几乎空)→ 不能用 dump bounds,只能**按固定分辨率截图目视/比例算坐标**做 tap。底栏各 tab 中心坐标先截图确认再算。**每次导航前先 reset 到已知态**(force-stop + 重启到首页),避免停在上轮遗留页导致坐标错位。

---

## 1. 工具链路(两端对称)

两端各备一套「截图 / 录屏 / 拉起页面 / 点击滑动输入 / 抓节点树 bounds / 对比 / 落盘」命令,一一对称。以 Flutter(源,adb)⇄ HarmonyOS(目标,hdc)为例:

| 动作 | 源真值端(如 Flutter/adb,一手真值) | 目标端(如 HarmonyOS/hdc,被测) |
|---|---|---|
| 截图 | `<源端 screencap>` → png | `<目标端 snapshot>` → recv(注意目标端可能只吃特定格式,如 .jpeg) |
| 录屏 | `<源端 screenrecord>` → pull | 若目标端录屏 CLI 未实测确认 → 兜底 = 连拍截图序列 |
| 拉起页面 | `<源端 am start -n pkg/activity>` | `<目标端 启动命令 -b bundle -a ability>` |
| 点击/滑动/输入 | `<源端 input tap/swipe/text/keyevent>` | `<目标端 uiInput click/swipe/inputText>` |
| 抓节点树+bounds | `<源端 dump>` → 读 XML/JSON bounds | `<目标端 dumpLayout>` → recv 结构 |
| 对比 | 见 §3,裁剪同区**并排像素 diff**(禁信全屏缩略图) | 同左 |
| 落盘 | `.ai-workspace/screenshots/<date>-<slug>/` + 更新 INDEX | 同左 |

### 自动化边界(诚实标注,按实测教训)
不同目标端 stack 的自动化各有触发不出的手势,必须实测标注:
- 某些**嵌套 Scroll 折叠/吸顶**自动 swipe **触发不出**;layout dump 也**分不清**吸顶正常/坏。
- 部分系统会**拦截 long-press**(被系统级 AI / 手势识别接管)。
- ⟹ **导航 / 点击 / 元素存在性 / 几何 bounds 对比** 用自动化;**手势重**(拖拽、嵌套滚动)和 **long-press** 回退**人工录屏 + 分步脚本**。不硬套自动化拿假数据。

### 目标端构建(固定前缀,坑随实测沉淀)
```bash
source <目标端 SDK 环境脚本>
<清掉会污染路径的环境变量>                 # 不清 → 构建工具路径被改 → silent fail
# 在 worktree 根跑对应 product / bundle
<目标端 assemble 命令>
<目标端 install -r 命令>                    # 装前必查产物 mtime > 源码 mtime,否则装的是旧包
```
构建环境的具体坑(路径转换 / product-bundle 映射 / build ctx vs bash)逐条沉淀进目标端知识库。

---

## 2. 每项修复回路(6 步,逐项复用)

```
① 反抽真值   grep+Read 源真值端 file:line 抽 4 维(节点/数值/资源/行为)
             + 在源真值端真机截图/录屏/自动化驱动 = 一手真值
② 定现状     在目标端截当前状态 → 裁剪并排源端 → 量差异
③ 修         按真值改目标端代码(禁凭印象);先查知识源(见 §3.5):
             知识库命中 → 直接套已沉淀解法;未命中 → transpile-rules / 目标端 KB
④ 构建装机   source env → 清污染变量 → assemble → install(验产物 mtime)
⑤ 双端验收   §4 三层
⑥ Gate       视觉≥5 元素一致 + 交互逐条 pass;❌≥2 → 回③,不放行
```
纪律:**手机先全绿,再进平板**;平板独立一轮(套目标端各自的宽度缩放模型),不复用手机结论。

---

## 3. 对比脚本(可复用)

一个通用像素对比脚本(node + 图像库):裁剪指定区域 → 两端并排 → 输出 diff 图 + 像素差率。用法见脚本头注释。落图统一进 `.ai-workspace/screenshots/<date>-<slug>/`。

---

## 3.5 知识源:目标端沉淀知识库(回路第③步先查)

把目标端 stack 的平台知识沉淀成可检索知识库(按类分文件,统一 schema)。修每一项前**先按症状词查一次**,命中即套已验证解法,不重复踩坑。两种查法:

**① MCP 工具(推荐)** — 注册后直接调语义+词法混合检索的 lookup(跨语言可用)。首跑下嵌入模型;corpus 改动后重跑 embed。

**② CLI 兜底(no-dep,纯关键词)**:
```bash
node scripts/corpus-lookup.mjs --n 5 "<英文症状词>"
node scripts/corpus-lookup.mjs --cat verify "<限类症状词>"
```

回路各步对应类:③修→UI/state/语言/translate/resources;④构建→build;⑤验收→verify;调试报错→debug;性能→perf;体验/合规→ux/security;数据→data 等,按目标端知识库的分类走。

**跨语言检索**:知识库 triggers 建议**双语化**(中英),检索层用**混合检索**(embedding cosine + 双语 triggers 词法)——中文症状可查到英文条目,反之亦然。**新增/改条目必保持双语 triggers**。

---

## 4. 三层验收(每项按可测性走对应层,不是都塞单元测试)

**① 单元测试(纯逻辑项)** — 目标端 stack 的单测框架,跑在 host 快。
适用:格式化、选中态模型、草稿序列化 round-trip、校验+冷启 hydrate、状态机、数据 keying 等**可抽纯函数**的逻辑。冷启型状态(volatile storage 重启即丢)必测重启 hydrate 路径。

**② 边界测试(每项 edge-case 矩阵)** — 进 tracking 矩阵逐个跑。
通用边界:空/单/多数据、min/max、跨年/年末、无数据分支、键盘上/下、**所有视觉项 × dark/light 两态**。

**③ 双端对比(视觉+交互项)** — §2 命令把两端驱到同态 → 裁剪并排像素 diff / 交互录屏对比。
gate:≥5 元素一致 + 交互逐条 pass,❌≥2 回炉。

分工:**纯函数 → 单元测试兜底防回归;纯视觉/交互 → 自动化驱动 + 双端 diff**;两者叠加 = 逻辑对 + 长相对。

---

## 5. Tracking 矩阵

每个批次维护一张矩阵(见对应 `.ai-workspace/` tracking 文件),列:
`# | 模块 | 问题 | 源真值端 ref(file:line) | 现 WIP 状态(🟢对/🟡不对/⚪没动) | 修复策略 | 单元测试 | 边界 | 手机验收 | 平板验收 | gate`。
全程只认这张表,做完一项勾一项。

---

## 6. 对比即扫异常(强制)

每次双端对比,**不只看目标项**。若截图暴露**任何**与源真值端不一致的界面异常(错位 / 溢出 / 截断 / 颜色 / 间距 / 缺失 / 浮层 / 字号 / 换行等),即使不是当前反馈项:

1. **登记**到 tracking 矩阵『额外异常(对比中发现)』段(位置 + 现象 + 源端真值)。
2. **低风险能当轮修的 → 当轮一并修**(同页同组、改动小、不破他处)。
3. **高风险 / 大改 / 跨页的 → 标记待评估**,单列后续项,不擅自大改。
4. 每轮委派执行器的 prompt 必带此指令;review 时协调端也主动扫对比图找非目标缺陷。

> 依据:对比截图发现的界面异常一并修复,不放过对比暴露的非目标缺陷。
