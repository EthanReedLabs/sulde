---
name: writing-task-md
description: 协调端写 task md 给前端 Dev(Android/iOS/Web 等)派活的完整规则。当用户说"写个 task md / 派活给 Dev / 给某端 Dev 写任务 / 派单 / 写 fix task / 写 audit task / /assign 准备 / 协调端写指令"等触发词或语境时必 invoke。覆盖:6 步审单 / 起草前 baseline 实证(含运行期 binding / 字段值映射 / crash 关键词澄清等扩展步)/ 3 维同步铁律 / contract-based 风格 / 能力档选择 8 问 / 目标 Claude Code 或 Codex 宿主原生派单 / 视觉对齐强制证据 / 防 N+1 round / 上下文压缩后 metacog / worktree 隔离。
---

# 协调端写 task md 完整规则

> 真值来源:协调端项目 CLAUDE.md §给终端写指令规则迁出的 skill。所有更新进本 skill,不进 CLAUDE.md。
> 占位符约定:`<docs-hub>` = 文档/设计真值中心目录;`<frontend>` = 任一前端工程(Android/iOS/Web…);`design-truth` = 设计真值(`.pen`/Figma 等导出的视觉真值,即 pen-truth 概念的通用名)。

---

## §0 写 task md 前必跑 6 步审单(强制)

写任何 task md 前**必跑 6 步**(缺一不写,防协调端凭印象 / 单维度数据源 / 凭印象不查技术真值 / 忘记派发过的任务复发):

| Step | 内容 | 防的反模式 |
|---|---|---|
| **0** | Read `<docs-hub>/.ai-workspace/baseline/latest.md`(SessionStart 已注入)+ grep 各 frontend handoff archive 近 14 天 + `git log --oneline --since=14d` 各 frontend — 验证"这件事是否已派/已完工" | 协调端忘记派发过的任务 |
| **0b** | **fix / bug 类 task md 前必查 Layer1 知识库前车之鉴**:跑 `bash <docs-hub>/_bugbook/scripts/review-similar.sh "<关键词>"` + grep `<docs-hub>/_bugbook/INDEX.md` 找同类 bug;命中 → task md §0 引"前车之鉴"摘要(根因 + 教训 + 修法),不重复踩坑 | 知识库回填回路「修前必查」— 与 baseline §7 沉淀欠债 forcing function 配对 |
| 1 | Read design-truth/{pageId}.md + .png(多模态识图,不只 JSON 节点)| 设计稿不导 .png 凭文字猜形态 |
| 2 | grep PRD INDEX § + API SPEC INDEX(对照接口字段)| 单维度数据源 → 真数据返工 |
| 3 | Read 各 frontend 当前实现(关键文件 + git log -5)+ `dual-platform-progress.md` 对照表 audit | 多端 Spec 不对称 / 进度不同步 |
| 4 | WebFetch / WebSearch 技术真值(平台官方文档 / framework bug / API behavior)— 涉及框架行为 / 已知坑 / 兼容性必查 | 凭印象不查技术真值 |
| 5 | 写 task md 含 3 段:① 3 维对照表 ② 反例(不能做什么)③ escalation 候选预登记 | 漏 sweep handoff escalation |
| 5b | **时序约束自检**:task 涉及 onAppear / onViewCreated / onCreate + 有批量渲染(列表绑定 / 媒体初始化)?→ task md 必含"时序约束"段(动画期间禁主线程重渲 + 具体 delay 写法)。例外:用户主动触发(下拉刷新/tap)无需 delay | 进场动画 jank 多端对称返工 |

### Step 0 强制铁律

- SessionStart hook 已自动注入 `<docs-hub>/.ai-workspace/baseline/latest.md` — 不再 grep 也能看到真值
- 派 **audit subagent** 前,subagent prompt 必含 Step 0 模板:
  ```
  Step 0(强制):Read `<PROJECT_ROOT>/<docs-hub>/.ai-workspace/baseline/latest.md`
    + ls `<frontend>/.ai-workspace/handoff/archive/{近 14 天}*.md`(对每个 frontend)
    + git -C <frontend> log --oneline --since=14d
  回报"这个领域近 14 天已做了什么"摘要,再做 audit。
  ```
- 协调端凭看代码下结论"已 wire / 未 wire"前必 git log 验证当前 commit 是不是协调端自己 task md 跑出来的

**判定线**:6 步任一缺 = task md 不合格,Dev 跑出来回归 = 协调端责任。
**Gate1 判定线**:fix / bug 类 task md,若 Layer1 知识库存在同类 bug 却未引"前车之鉴"段 = 不合格(修前必查回路断裂)。

---

## §0.5 起草前 baseline 实证(强制 — 防协调端凭印象起草 master fix)

> **关联反模式**:`<docs-hub>/ADR/coordinator-impression-based-dispatch.md`
> **设计动机**:**§0 6 步审单**侧重"看哪些文件",**§0.5 baseline**侧重"verify 字面引用真实性"(防 stale Read + 凭印象 + scope 扩散 + scaffold 与 design-truth cross verify 缺失)。
> **两段不替代**:§0 后必跑 §0.5,任一缺 → hook `check_task_md_baseline.py` 直接拒 Write(段标必含 `§起草前 baseline 实证`)。

### §0.5.1 引用真实性 baseline(必跑 + 引用 grep 输出 / 行号)

每写 task md 前**必跑**以下步骤,产物**贴入 task md frontmatter 下方"§起草前 baseline 实证"段**(无段 = 不合格)。Step 1-5 为常规起草必跑;Step 6-20 为按触发条件追加(触发即必跑)。

| Step | 必做 | 输出格式 | 防的反模式形态 |
|:-:|---|---|---|
| **1** | `git -C <frontend> log --since=14d --oneline`(对每个受影响 frontend) | 列 N commit(hash + msg),命中本 task scope 的标 ⭐ | stale Read:协调端基于 working tree 草稿 ≠ 实际 develop 状态起草 |
| **2** | `grep -rn "<UserIntent / Action / API 真名>" <frontend>/<source dir>` | file:line + 命中代码片段(≤ 3 行) | 凭印象用错 symbol 名(意图名 vs 真实回调名)|
| **3** | `git log -S "<symbol>" --oneline --since=30d` 反向搜索。**feature 类 task md(新功能 / Download / Share / 播放 / 上传 类)起草前必跑** `git log -S "<feature_func_or_state_name>"` 各 frontend verify 该 feature **是否已存在**;若命中 commit → **fail-fast 拒生成,prompt 协调端 review feature 真值**——"严禁不动 X"可能语义是"X 已实施且本 task 不再动",非"X 未实施" | 命中 commit hash → ① 区分 Dev 自发实施 vs 设计稿真值 vs 协调端补充 ② **feature 已存在 → fail-fast 拒生成** | 把 Dev 自发违规当"应该如此"写入 design-truth 补充段;误读 task md §严禁 = "未实施" 起重复 feature task |
| **4** | `bash "<docs-hub>/design/query-scaffold.sh" --list` / `query-scaffold.sh <id>` 查 scaffold 契约 + `grep -rln "<scaffold class>"` 跨各 frontend 实证全站既定 usage | 列必用 scaffold + 同款 host 既定实践 workaround | 禁止规则脱离既定实践;漏 sweep scaffold 调用点 |
| **5** | **cross verify scaffold 实际数值 vs design-truth 真值数值** | 对照表 `scaffold 字段 / scaffold 实际 / design-truth 真值 / 一致?` | scaffold 自身偏离设计真值(例:某 TopBar 组件字号 vs design-truth) |
| **6** | **verify HEAD 最新 commit**:`git -C <frontend> log <main-branch> --oneline -10` quote 到 baseline 段;不允许只看历史 commit | quote 最新 10 commit | task md quote 旧 commit 但主干已有 Dev 对话间自发 follow-up,协调端没自检 git log |
| **7** | **Adapter / DTO 层 JSON key 字段名 cross-verify API SPEC + 各端序列化默认值** | 对照表 `字段 / 各端 CodingKeys/SerialName / API SPEC 真值`;若一端显式 rename(`snake_case`)必 verify | 一端 rename / 另一端用默认 camelCase / API SPEC 第三方不一致 → backend 422 |
| **8** | **凡 quote 各端代码必 `git show <commit>` 或 Read 最新文件 verify 原文** | 不允许 quote 历史 audit subagent 报告 / conversation summary 内的代码段 | task md quote 旧值,实际代码已变(凭印象抄旧 audit)|
| **9** | **字段值映射 cross-verify**(用户报 backend 拒 / 字段相关 bug 时**第一步**):派 frontend 抓包 task(Charles/proxy)抓 same operation request body **全字段 JSON 对比**,不允许 audit code line by line 先 | 对照表 `字段 / 各端 request body 真值 / API SPEC contract / 等价?`;**字段名相同 ≠ 字段值正确**,必比真值 JSON | 双端字段名一致但值映射错(传主键 vs 传分类 ID),多轮 audit code 看不到,抓 1 次就暴露 |
| **10** | **真机截图 ≠ 代码层 gap**(用户报"UI 不对 / 空白"时**第一步**):`ls` 各端 target 目录 + grep view 文件数验证现有实现规模,**不允许凭真机截图反推代码层 gap** | 对照表 `目录 / 文件数 / 行数 / 估算实现度`;真机空白可能因 build/install/数据未推/state 未到达,而非代码缺失 | 凭真机空白推"某端 0 实现"建议从 0 接,实际 view 已全建,真因是数据链路断 |
| **11** | **业务真值文档(BTM)引用必填**:task md 涉及核心业务模块**必先 Read 对应 BTM** `<docs-hub>/业务真值/{module}-truth.md` + INDEX,把关键 file:line / SSE 字段落点 / Model join 关系 / 各端对照表 **直接 quote 进 task md baseline 段**;BTM 缺该模块 → 先派 audit subagent 沉淀 BTM,再起 task md | baseline 段含 `BTM doc 路径 + 引用维 N + quote 关键 file:line` | 无单一真值源,task md 凭印象抄字段名 → join 从未实现 / 镜像漏检差异 |
| **12** | **gating / 解锁数派生类 task 必先实证 thin step running 行为**:review approve gating 契约前必让 Dev 实证 "step running 时 step 内字段是否有数据填充 view";thin step(只 thinking 无 result_summary)**不要 "running 也算已达"** — 解锁后空白页用户体感更差 | review approve 段必 quote Dev 实证;列 thin step 清单;新契约必显式标 "success only" 或 "running 也算已达 + 数据填充实证 line N" | 凭"通用 UX 模式"想当然 "running 也算已达" → 用户真机推翻,改 success only |
| **13** | **实装/视觉/导航类 task 必 quote design-truth nodeId 真值 OR escalate user 拍板**:fullScreenCover / push / sheet / 就地播放 / Modal / Toast / Dialog 决策必基于 **design-truth 视觉契约 nodeId line N**;若 design-truth 缺该交互节点 → **escalate user 拍板**,**不允许凭 "iOS 通用 UX 模式" / "Android Material 模式" 决定** | "视觉契约 / 导航形态"段必 quote design-truth `{pageId}.md` line N 或 nodeId;缺则标 `escalate user 拍板` + 不签发实装方向 | 凭"通用模式"写 fullScreenCover,用户期望当前页内播放,从未 quote design-truth nodeId |
| **14** | **同一问题 2 次修不好 → 第 3 次起 task md 前必 invoke review skill**(详 §0.5.7):同一 bug / 同一用户真机反馈在 2 次 fix task md(已 merge 主干 + 用户真机 verify)后**仍未解决** → **协调端 hold 起新 task md**,必先 invoke ≥1 review skill 实证真因 + 推荐最小改动,review report 出来后才签发 | frontmatter 加 `review_invoked:` 字段引用 review skill 名 + report 路径;无 review report = 拒生成 | 没在重修前 stop + review,直接起第 3 次 task md 方向错,累计多轮真机 verify 浪费 |
| **15** | **crash fix task md 必先 verify 甲方实测 version vs 主干 version**:验收期甲方装包 ≠ 当前主干;crash 报告必先核实"甲方实测 version" — 若旧 build 已修 → 起"出新交付包"而非"重复 fix" | frontmatter 加 `acceptance_build_verified: true/false` + quote 甲方 version + 主干 version 对照;缺 = 拒生成 | crash task md 凭甲方"crash"反馈起,实证旧版已修,甲方装的是更老交付包 |
| **16** | **crash 二字关键词必先澄清 / grep 设计 token,不直接判 crash**:甲方反馈 "XX 黑屏 / 崩 / 卡死" 可能是 ① 真 crash ② 加载占位被感知 ③ 设计上没有的功能 ④ 性能慢被感知;②③④ 不应自动判 P0。起草前必 grep `placeholder / loading / bg_*_cover / transparent` 设计 token + Read design-truth verify | `§0 baseline` 必含"crash 关键词澄清" — grep 设计 token 命中 + Read design-truth verify;若设计上有占位 / 无该交互 → 标 ❌ 非 crash + escalate user | 凭"黑屏"二字推 P0 crash,实证是设计指定的深灰加载占位被感知 |
| **17** | **crash fix task md 必含 FATAL stack quote(真栈)而非"候选根因清单"**:改"真栈 → 真因分析 → fix"单一路径。起草前必从 user / Dev / handoff 拿真崩溃栈;若无栈 → 标 audit-only task 先抓栈再起 fix | `§0 baseline` 必含 `FATAL stack quote` 段(真栈引用 file:line + 进程 PID);无栈 = 标 audit-only 先抓 + 拒生成 fix;候选清单仅在真栈缺失时用且必标 ⏳ 待实证 | 凭技术名词假设推真因,实证不复现,真因是别处;1 行真栈胜过候选清单 |
| **18** | **跨 infra+feature 共享工具(logger/config/event bus 等)位置必基于 deps 实证**:指定模块位置前必 grep 依赖清单(`Package.swift` / `build.gradle.kts` deps 块 / `package.json` 等)看 call site 横跨的所有模块共同依赖;落最底层共同依赖。**禁凭"UI 类放 CoreUI"等直觉**,实际是 deps 单向性问题 | `§0 baseline` 必含 "目标模块 deps 实证" 段:列 call site 涉及模块 + grep deps 块输出 + 共同最底层依赖 quote;若 `cannot find ... in scope` release fail = 拒生成 | 指定 CoreUI,实证上游模块不依赖 CoreUI → release build fail;唯一共同依赖是更底层 CoreCommon |
| **19** | **symbol caller 实证 ≥1**:baseline grep symbol 命中后必跑 `git grep "<symbol>("` 双向看 caller 数;若 caller 数 = 0 → 标 dead code **不当 task md 真值落点**,继续 grep 实际 caller(真热路径) | baseline 引用 symbol 必带 caller 数 quote;`caller==0` = 拒生成 / 改实际热路径 | baseline 落点指向 0 live caller 死方法,真热路径在别处 |
| **20** | **runtime binding / observer / dispatcher / delegate 等 dynamic dispatch 真因必先 audit-only 实证**:baseline 触发条件加 **"运行期 binding 敏感模式"标识**:`setFragmentResultListener` / `addObserver` / `addCallback` / 依赖 swap / `delegate?.method` / TCA `cancellable(id:)` 等 dynamic dispatch 真因**静态 grep 无法捕获**(只看 declaration,看不到 runtime binding 是否 wire 通);命中即必先派 Dev audit-only(log / 真机 audit / Inspector)抓 runtime evidence,**static grep + runtime audit 必双管齐下于真因诊断之前** | `§0 baseline` 含 dynamic dispatch symbol 命中 → 必加 "runtime audit handoff 引用" 段(audit handoff 缺 → 标 audit-only task 先);**禁** 候选清单只依据 static grep | 静态 grep 得"只缺 render",真机实证是 FragmentManager 错配监听永不触发(假成功 "添加成功但未生效")|

### §0.5.7 Step 14 review skill 清单(同一问题 2 次修不好场景)

| skill | 适合场景 | 工时 | 触发 |
|:-:|---|:-:|---|
| **`Agent`(general-purpose audit subagent,opus)** ⭐ 高频核心 | 真因不定位 / 多端代码对比 / PRD/API/design-truth 三方实证 / git log 反推 | ~15-30min opus | 协调端 invoke `Agent({subagent_type:"general-purpose", model:"opus", prompt:...})` |
| **`mattpocock:grill-me`** | 方案 stress-test / 反推"更简单解" / 找最小改动 | ~10min 交互 | Agent 在当前宿主可用时调用 |
| **`mattpocock:zoom-out`** | 陷入局部细节 → 跳出看架构层根因 | ~5-10min | Agent 在当前宿主可用时调用 |
| **`mattpocock:diagnose`** | 复发型 bug / 多端真因系统化诊断 | ~20-30min | Agent 在当前宿主可用时调用 |
| **`superpowers:verification-before-completion`** | 完工前 verify(Dev handoff 真值审计 — 防 handoff "已修"自报 fail) | ~5min | 协调端 invoke |
| **`/ultrareview`**(系统命令)| 大改 / 高风险 / 多端架构改造 PR 级 review | ~10-15min 异步 | 宿主可用且获原生高风险/计费 Allow 后由 Agent 调用 |

**最高效组合**:
1. **audit subagent**(实证真因 + 多端代码 + 真值源 PRD/API/design-truth)— **必跑**
2. **grill-me**(stress-test 真因 / 找最小改动)— 可选,当前宿主可用且任务收益足够时由 Agent 跑
3. **verification-before-completion**(Dev 完工 handoff 来时三联实证)— Dev 完工后跑

**Step 14 强制铁律**(违一即不合格):
- ❌ 同一问题 2 次修不好,第 3 次直接起 task md 不 invoke review = 拒生成
- ❌ review report 凭印象 / 不实证(必 file:line + design-truth/PRD/API quote)
- ❌ 跳过 review 直接派 Dev(因"积分浪费"假象)— 实际没 review 直接派的浪费远大于 review 工时
- ✅ review 后才决定:① 起新 task md(基于 report)② hold 等真值补齐 ③ user 决策(产品级)

### §0.5.2 task md frontmatter 下方强制段(模板)

```markdown
---
- assignee: ...
- branch: ...
- capability_tier: ...
---

# {任务标题}

## §起草前 baseline 实证(协调端必填 — §0.5 强制)

### Step 1:近 14 天 commit
- git log --since=14d 每个受影响 frontend commit:
  - {frontend-name}:
    - {hash} {msg}(本 task scope:⭐ / 旁证)
    - ...

### Step 2:UserIntent / Action / API 真名 grep
- `grep -rn "<keyword>" <frontend>/<source dir>`:
  - {file}:{line} `{actual symbol}`(verify literal name vs intent name)
  - ...

### Step 3:reverse symbol 反向搜索
- `git log -S "<symbol>"`:命中 {hash} {msg}
- 来源判定:{Dev 自发实施 / 设计稿真值 / 协调端补充 / 用户决策}

### Step 4:Scaffold 既定实践 sweep
- `query-scaffold.sh --triggers {keyword}`:命中 scaffold X({file:line})
- 同款 host 既定实践 grep:命中 N 处(列 file:line)

### Step 5:Scaffold 数值 vs design-truth 数值 cross verify
| 字段 | scaffold 实际 | design-truth 真值 | 一致? |
|---|---|---|:-:|
| {field} | {scaffold value} | {design-truth value} | ✅ / ❌ |
| ... | ... | ... | ... |

**冲突项处理**:
- design-truth 优先级 > scaffold → scaffold 偏 → 必改 scaffold(架构 task)/ 必标 task md "数据源冲突段"
- design-truth 缺数据 → 信 scaffold + 标 "design-truth 缺失,handoff 协调端补"

### Step 6-20:按触发条件追加(命中即填)
- crash 类 → §0.5.1 Step 15-17(acceptance_build_verified / crash 关键词澄清 / FATAL stack quote)
- 字段/接口类 → Step 7 / Step 9(DTO key cross-verify / 抓包字段值对比)
- 共享工具落位 → Step 18(deps 实证)
- dynamic dispatch 真因 → Step 20(runtime audit handoff 引用)
- 同问题 ≥3 次 → Step 14(review_invoked 字段 + report 路径)
```

### §0.5.3 §scope 自检 3 问

写 task md 前自问:

| # | 问 | 答 → 处理 |
|:-:|---|---|
| 1 | 用户原话精确说"修 X"? | 是 → scope 严格限于 X,不扩 |
| 2 | 我发现"相邻问题"(其他 frontend 同款偏 / 同款页全站 sweep / 顺手 fix)? | 是 → handoff 写给用户拍板,**不主动扩 scope** |
| 3 | 多 frontend 用户都报? | 否 → **不自动派其他 frontend**,该 frontend 的 task md 起草后 hold |

**判定**:scope 扩散嫌疑 = task md 顶部加 §scope 段引用用户原话 + 列扩散选择 + handoff 给用户拍板。

### §0.5.4 数据源冲突段(scaffold + design-truth 矛盾时强制)

凡 task md 涉及 scaffold(项目通用组件如 TopBar / StateView / Router 等;实际名见 `<docs-hub>/scaffold-map.yaml`),Step 5 cross verify 若发现 scaffold 偏 design-truth → task md 必含:

```markdown
## 数据源冲突段(scaffold 偏 design-truth)

### 实证
- design-truth §X 真值:{真值数据}
- scaffold 实际值:{scaffold 数据}
- 偏差量化:{字段差异 / 数值差异}

### 优先级
design-truth > scaffold > 业务层 — Dev **不允许业务层 override scaffold** 解此偏差

### 解法
- (A) 架构 task 改 scaffold(推荐 — 影响全站 N 页)
- (B) 不改,接受 scaffold 现状(若 trade-off 评估改造 ROI 低)
- 协调端定夺 → task md 内显式标方案
```

### §0.5.5 协调端 design-truth 补充前 sweep

协调端在 `<docs-hub>/design-truth/{pageId}.md` 加补充段(标"协调端补充"/`coordinator-supplement-*`)前**必跑**:

| Step | 必做 | 防 |
|:-:|---|---|
| 1 | `git log -S "<element keyword>"` 反向搜索 N 月历史 | 区分:Dev 自发实施 vs 设计稿真值 vs 用户决策追加 |
| 2 | design-source MCP `batch_get` 该 pageId 真值(`mcp pencil` / `mcp figma` / ...) | 确认原稿是否有该元素 |
| 3 | 用户原话 review — 产品决策追加 / 还是不满 Dev 自发违规? | 区分意图 |

**3 项交叉判定**后再写补充段,且**明标来源**(`source: Dev 自发 / 设计稿真值 / 用户决策 / 协调端补充`)。

### §0.5.6 拒生成机制(§0.5 强制效力)

任一 baseline step 缺 / scope 自检嫌疑未处理 / 数据源冲突段缺 → **协调端 self check fail**:

- ❌ task md 不签发(不输出派单短指令)
- ❌ design-truth 补充段不写入
- ✅ 输出"baseline 实证缺 X,需补 grep 输出再生成"

协调端自检失败时,**先补 baseline 再起草,不让 Dev 跑半成品**。

### §0.5.9 audit only task md 完工自检

**触发**:协调端写 `audit only`(不改代码 / 不 commit / 不 merge)task md 时,frontmatter 标 `分支:N/A`、`worktree:N/A`、`类型:Dev → 协调端 audit handoff`。

audit task 完工铁律(违一即不合格):

| 铁律 | 描述 | 反例 |
|:-:|---|---|
| 1 | **临时调试 Log 完工必删** — 加 `[XxxDiag]` 标签的 Log 仅本地真机 verify 用,**不 commit 入 git**;handoff 写完后 Dev 执行 `git diff` 应 0 改动 | 临时插桩未删入 commit |
| 2 | **handoff `## scope 自检 — 未动源码 verify` 段强制** — 引用 `git status` 输出 clean + `git diff` 0 改动证据 | worktree 未 commit 但 user install build → 装到半成品 |
| 3 | **audit handoff 类型显式标"Dev → 协调端 audit handoff(不 commit / 不 merge)"** — 防 baseline 脚本把 audit handoff 误统计为 fix task 完工 | 同 §handoff 概念隔离(类型 1 跨终端 handoff)|
| 4 | **多端 audit 对照实验同款 Log 标签** — 各端用同款 `[XxxDiag]` 标签 + 同款 grep 关键词,handoff 含各端命中数对照表 | 双端 Log 标签 / prompt 语言对齐 |
| 5 | **真因实证驱动**(不主推方案)— audit handoff 列 ≥ 3 候选真因 + log / grep 实证 + 协调端 review 后决定 fix 方向 | 防 task md "主推方案" 诱导 Dev 第一轮无效 fix |

**判定线**:任一缺 = audit handoff 拒签收 / 协调端不基于 audit 起 fix task md。

---

## §0.6 起草前防 N+1 round checklist(防"差一点"循环)

写 task md 前协调端必跑 6 步 audit 反 fix 一直差一点(N+1 round 模式):

### Step 1 — 真值完整性 audit(防"schema doc 留关键字段不留完整 raw")

新功能 / 新 API / 新协议**首次实施前**必跑完整真包反推 + 整理 superset doc(不止"关键字段"反推)。判定线:
- 若 raw 真包(curl chain / 抓包)已抓 → 整理 complete schema doc(`task_name` 大小写真值 / 嵌套层次 / typo / 所有字段名 / structured message 类型枚举)
- 若 doc 只反推关键字段 → 后续 round 每暴露一个新 gap = 协调端责任(本 task 修真值同时补 doc)
- 协调端 `phase-X-complete-schema.md` 是 superset,后续 task md 必引用

**判定线**:user 报新需求时 doc 不足覆盖 → 先派 subagent 整理 superset doc 再起 task md

### Step 2 — 同源 audit 5 问(防"scope 严格 cover 用户原话漏同源")

user 报"修 X"前必跑同源 grep:
1. **同模块**:X 所在 module 是否还有 unwired / unmapped 相似元素?
2. **同字段**:X 数据字段(field name)在各端 / 上下游是否有同源遗漏?
3. **同 commit 史**:近 N round 修过类似问题没?是否漏掉某个 stage?
4. **同 PRD 段**:PRD 同段还有什么 spec / acceptance 未实施?
5. **同 design-truth 节点**:design-truth 同 page / 同 component 还有什么节点未 wire?

**判定线**:5 问任一命中 → task md scope 必扩 / 或在禁区注明"已实证不命中"

### Step 3 — user 视角 mental walkthrough(防"代码层 audit 漏用户感知 bug")

起 task md 前 mental walkthrough 用户真机操作流:
- 用户**怎么操作**(冷启 / 点击路径 / 等待 / 切换 tab)?
- 用户**期望看到什么**(数据 / 视觉 / 反馈 / 动画)?
- 用户**实际会看到什么**(数据 ready 前 / 加载中 / 失败态 / 边缘 case)?
- 反馈机制(Toast / overlay / 进度)是否对齐用户感知?

**判定线**:walkthrough 任一步无对应实施 → task md 必加;**协调端 grep 看不到用户感知 bug**(animation / state sync / 反馈缺失)— 必 mental walkthrough

### Step 3.5 — Verify Path Reality Check(防"虚构 verify path / 死代码 guard")

每个 verify path / reducer guard / banner 提示 case 自问:**"user 能否物理到达此 path 的起点?"**

- 该 view 显示前提是什么 state?(必 grep `<feature>Active` / `is<X>Visible` / `fullScreenCover(isPresented:)` 等 entry condition)
- 该 state set 时,其他 state 字段是否**原子写**?(必 Read reducer 同 case 内所有 state mutation)
- 是否存在 "view 显示 + state.X = nil" 的**中间状态**?(必跑双向 audit:进入 reducer + 退出 reducer)
- 若 PRD / 设计稿明确**无此交互**(如 banner 提示 / N case Toast),协调端**绝不自行设计补充** — 用户明确否认 = 设计稿真值,不补

**判定线 1**:命中 "中间状态不存在" → 此 verify path 虚构,**删 task md verify step + 删 reducer guard**(不留 defensive 代码)
**判定线 2**:命中 "PRD/UI 无此交互" → task md 改动**取消**(凭印象设计违反"不凭印象下发"铁律)

### Step 4 — scope 内含"相邻 audit 引导"(防 Dev 严守 scope = 漏点跟着 task md 走)

task md scope 段加 **"相邻 audit 列表"**(Dev 不扩 scope 但 grep 标记):
- 实施 X 时顺手 grep 同模块 N 个文件,**标记**所有同源相似元素位置
- 若 grep 标记**全部 cover**(本 task scope 内已含)→ 无 escalation
- 若 grep 标记**有未 cover**(本 task scope 外)→ handoff escalation 列**精确 file:line + 同源类别**

**判定线**:Dev handoff escalation 缺"相邻 audit 标记" → 下次同问题再爆 = 协调端没设引导

### Step 5 — 派 subagent 二轮完整性 review(防"协调端 audit 单视角")

复杂 task md(scope > 5 文件 / 跨 ≥ 2 module / 跨多端)起草后**派 subagent 做"我的 audit 是否完整"二轮 review**:
- subagent prompt 含"反问 audit 5 问"(同 Step 2)+ "user 视角 mental walkthrough"(同 Step 3)
- subagent 输出 risk 清单 + 补漏建议
- 协调端 review subagent 输出 + Edit task md 补漏

### Step 6 — 真机 verify 频次目标(防真机反馈环路慢)

每 round 完工后真机 verify 不超 24h:
- Agent 负责 build、安装、启动、触达改动路径、采集日志/截图并判定结果
- 若某端真机 `unavailable` → Agent 优先恢复工具链或切换可验证设备，不接受多 round 累积代码 audit 不真机
- 只有连接、解锁或现实环境操作确实无法自动化时，才请用户完成该物理动作；随后 Agent 自动重探测并完成剩余验证，不要求用户回贴命令输出或固定短语
- 真机 verify 失败 → 协调端 Agent 在 24h 内生成并推进 follow-up task md(不放置 backlog 长)

**判定线**:某 round 完工 ≥ 48h 无真机 verify → 协调端 Agent 自动建立带 blocker 的 ticket；仅物理设备时机需要人决定时才询问

---

## §0.7 上下文压缩后协调端 metacog 强制规则

**触发**:本 session 看到 `<conversation summary>` 或 SessionStart compact hook 输出后,协调端**凭印象失误风险 ×10**(因为 conversation summary 只保留 "what happened" 不保留 "ground truth source")。

**核心规则**(单一不可妥协):

发现问题 / user 报"X 不对" / 起 task md / 派 audit subagent — **任一时机起草前必跑 3 维真值 cross-verify**:

| # | 维度 | 必跑命令 | 必 quote 到 task md / 报告 |
|:-:|---|---|---|
| 1 | **需求/PRD** | `grep -n '<feature>' <PRD>-INDEX.md` → Read offset:N limit:60 | PRD 原文段 + 章节号 |
| 2 | **接口/API** | `grep -nE '<endpoint>' <API SPEC>-INDEX.md` → Read offset:N | API SPEC 原文段 + endpoint + 必填字段校验 |
| 3 | **UI/UX 交互** | Read `design-truth/{pageId}.md` + `.png`(若涉及视觉)+ user 真实操作截图 / 录屏(若 user 提供)| design-truth 节点真值 / user 操作流程描述 |

**禁忌**(命中即触发拒生成):
- ❌ 引用 conversation summary 内的 "我之前 audit 过 X" 当成真值(summary 内 file:line 可能 stale)
- ❌ "我记得 PRD 是这么说的" / "我印象中 API 这样设计"(必 Read PRD/API 原文段)
- ❌ user 报"X 不对"协调端第一反应不是 grep PRD/API/UI 三方,而是猜测可能根因
- ❌ 起 task md 时只 grep 代码不 quote PRD / API / UI(协调端编 "凭印象设计" — 如 banner / 拦截交互 / 视觉 fallback)

**3 维冲突时优先级**:
1. **user 真实操作流程 / 录屏**(最强真值 — 当前实施真值)
2. **design-truth / 设计稿**(视觉 / 交互真值)
3. **PRD V3**(产品意图,可能是 future 完整版)
4. **API SPEC**(后端契约)
5. **历史代码 commit**(已实施真值,但可能是 MVP 工程妥协 ≠ PRD)

冲突时必在 task md 写 **"§数据源冲突段"**(§0.5.4)说明协调端取哪个 + 为什么 + user 是否决策过。

**How to apply**:
- SessionStart compact hook 触发后,**第一次接 user 新指令**:不调任何工具就回答 = 禁止(必先 Read 三方真值)
- task md 起草模板必含 **§0 真值实证 3 维段**(PRD quote + API quote + UI/UX quote 三段,缺一即 hook 拦截)
- audit subagent prompt 必含 "**禁止引用 conversation summary** — 自己 Read 三方原文 + quote file:line + 与 user 实际操作流程 cross-verify"
- 凭印象嫌疑发现后:**立即承认 + Read 三方真值原文 + 重写 task md / 重新 audit**

---

## §1 3 维同步铁律

任何功能 / task md / 反模式登记 / bug 修必做 **UI/PRD/接口 3 维交叉验证**,避免单维度数据源 → 真数据返工。

**3 维定义**:

| 维 | 数据源 + 入口 |
|---|---|
| **UI/UX** | `<docs-hub>/design-truth/{pageId}.md + .png` / design-source MCP `.pen`·Figma / `assets/` 真素材 |
| **PRD** | `<PRD>-INDEX.md` → line N → Read offset/limit |
| **接口** | `<API SPEC>-INDEX.md`(REST)+ SSE/streaming spec INDEX → endpoint / task_name → 字段 |

**5 步执行**:

1. UI 维 — Read design-truth + .png + grep 节点属性 → 提取 view 必含字段
2. PRD 维 — 找对应 §x.y → 提取描述字段
3. 接口维 — 找对应 endpoint / task_name → 提取接口字段
4. 生成 3 维对照表(必含段写入 task md):
   ```markdown
   | 字段 | UI(design-truth) | PRD line | 接口字段 | 一致? |
   |---|---|---|---|---|
   | 风格名 | {pageId} style_name | NNNN | style_options[].name | ✅ |
   ```
5. 冲突项处理:
   - UI vs PRD 冲突 → 按 UI(design-truth)
   - PRD vs 接口字段不匹配 → 协调端发邮件甲方解分歧(异步)
   - 3 维都冲突 → task md handoff §4 留 Dev 实施时反馈

**判定线**:缺"3 维对照表"段 = 单维度数据源 + 凭印象 双重违规。

**工时**:单页面 ~20-30min;多 stage 流程 ~1-2h;跨模块 ~1-1.5h。

详 `<docs-hub>/shared-rules/data-sources.md §3 维同步铁律`。

---

## §1.9 task md `§完工三步` 必用 git worktree 隔离(强制)

**铁律**:**所有 task md(各 frontend,无论单任务还是并行)必用 git worktree 隔离**,不允许同 working tree 直接 `git checkout -b` 切分支。

### Why

- Dev 跑 task A 未 commit,user 派 task B → 分支模式 stash 混乱 / worktree 模式互不干扰
- 多 task md 串行实施 → 分支切换易污染 dirty 状态 / worktree 各自独立
- handoff `git status -s` → 单 working tree 多任务 dirty 混杂 / worktree 清晰
- build cache(`.build` / DerivedData / `node_modules`)→ worktree 独立 build dir
- 协调端 audit → `ls <PROJECT_ROOT>/<project>-*` 1 行实证活跃 task

### 强制模板(task md `§完工三步` 段必含,替换原 `git checkout -b` 模式)

```bash
# §1 起 worktree(替换原 checkout -b 模式)
WORKTREE_DIR=<PROJECT_ROOT>/<repo-name>-<task-slug>     # 约定:<repo>-<slug>
git -C <PROJECT_ROOT>/<repo-name> worktree add \
    "$WORKTREE_DIR" \
    -b dev/<dev-name>/<task-slug> \
    <main-branch>

# §2 切到 worktree 实施
cd "$WORKTREE_DIR"
# ... build / install / 改代码 / 真机 verify

# §3 完工 commit(在 worktree 内)
# ⚠️ as-a 是 commit-only alias(已含身份 -c user.name + user.email),
#    不可写 "as-a add" / "as-a commit"(会展开成 "commit add" / "commit commit" 报错)。
#    正确:git add 裸用(staging)+ git as-a -m "..."(提交,身份自动)
git add <files>
git as-a -m "<拟人化 message>"

# §4 merge 主干(切回主 working tree 做,fast-forward 自动)
cd <PROJECT_ROOT>/<repo-name>
git checkout <main-branch>
git merge --ff-only dev/<dev-name>/<task-slug>

# §5 删 worktree + 删分支(完工后清理)
git worktree remove "$WORKTREE_DIR"
git branch -d dev/<dev-name>/<task-slug>
```

### 判定线(协调端写 task md 时 self-check)

- ✅ task md `§完工三步` 段含 `git worktree add` + `WORKTREE_DIR` 路径 + `git worktree remove`
- ❌ task md 仍写 `git checkout -b dev/xxx <main-branch>`(违反本铁律)
- ❌ 协调端假设"Dev 自己处理 worktree" — 必显式写命令

---

## §2 给终端写指令格式(基础 4 条)

1. 指令要能被受管 Agent 直接消费，不让用户复制、粘贴或自行拼接
2. 路径用绝对路径,避免歧义
3. 明确告诉终端用什么 skill + 该 skill 期望的输入格式
4. **任何超过 30 行的任务必须写 task 文件**(强制):
   - 路径:`<frontend>/.ai-workspace/tasks/{YYYY-MM-DD}-{slug}.md`
   - 调度消息缩到 1-3 行，只引用文件路径并由协调 Agent 直接派发
   - 例:`/assign 任务文件:.ai-workspace/tasks/{date}-xxx-fix.md`
   - **禁止**主会话把 200+ 行 prompt 交给用户搬运
   - task 文件结构标准:身份分支 / 视觉/数据/行为契约 / **复用思考** / 验证 / 禁区
   - 通用约束(必读 / 编译验证 / handoff)在各端 `/ui-impl` `/assign` skill 里硬约束,task 文件不重复写

---

## §3 task md = contract-based 非 boilerplate(强制)

### 禁(boilerplate-based)

```markdown
## 实施
### a. 新建 StylePickerBottomSheet.kt
\```kotlin
class StylePickerBottomSheet : BaseBottomSheetDialogFragment() {
    override fun onStart() {
        super.onStart()
        val dialog = dialog as? BottomSheetDialog ?: return
        // 50 行 BottomSheet 配置...
    }
    // ... 200 行完整骨架
}
\```
```

→ Dev 看到完整代码骨架直接 copy-paste,失去抽象判断机会,跨 picker 重复实现。

### 强制(contract-based)

```markdown
## 视觉契约
弹窗:居中圆角 sheet,370×699,顶部 56,圆角 20,dimmer 0.76,slide-in-bottom
(详见 design-truth/{pageId}.md §X 节点属性对照表)

## 数据契约
入参:selectedStyleId / 出参:fragment result key + delegate

## 行为契约
close X / Cancel / dimmer tap → 不写回 dismiss
Continue → 写回 selected + dismiss

## 复用思考(强制段 — Dev 必填)
- 公共 UI 模块是否已有同款基类 / RoundedImageView / GradientStrokeFrame?
  有 → 直接复用;无 → 本 task 顺手抽 + 写到公共 widgets/
- 当前视觉模式是否会在其他 picker / 其他页面再用?是 → 必抽公共控件
- handoff §X 必填"抽了哪些公共控件 + 哪些场景能复用"

## 反模式禁区
- 不要直接抄 BottomSheetDialogFragment 配置(此容器先天底部对齐)
- 不要用普通 ImageView(图片不跟随父圆角)— 必 ShapeableImageView
- 不要用 layer-list selector 做 stroke + fill(双层 radius 不一致 → 边角断裂)
```

### 判定线(协调端 task md 自检)

```bash
# 检查代码块数(连续 ``` 块 ≥ 6 = 风险给 boilerplate)
grep -c '^```' <frontend>/.ai-workspace/tasks/{file}.md
# 检查"复用思考"段(0 命中 = 违规)
grep -E "复用思考|公共控件|抽 .*widgets|widgets/" {file}.md
```

任一失败 = 不合格,必须重写为 contract-based。

### Android 特化清单(UI 还原 task md 必含)

| 视觉模式 | 必抽控件 / 必约束 | 路径 |
|---|---|---|
| 圆角图片 + centerCrop | `RoundedImageView`(扩展 ShapeableImageView)| `core-ui/widgets/image/` |
| 卡片选中态 gradient stroke + 圆角 | `GradientStrokeFrame`(自定义 FrameLayout)| `core-ui/widgets/card/` |
| 居中圆角 sheet 容器 + dimmer + slide-in | `AppCenterSheetDialogFragment`(基类)| `core-ui/widgets/dialog/` |
| Material Button inset 清零 | values/styles.xml 默认 style | core-ui values/ |
| RecyclerView inline expansion 视觉合并 | 单 ViewType + VH 内嵌 + bind 切 drawable 拆顶/底圆角 + margin=0 + 共享 stroke;禁"item 内独立 view 切 visibility" | drawable XML + Adapter VH 切 background |

### 多端实现路径预案

涉及"列表 inline expansion / 浮层与触发元素关联 / 圆角图片 / 渐变 stroke"等 UI 场景,task md 必给各端基于**平台规范**的实现路径(iOS Apple HIG / SwiftUI;Android Material Design / Jetpack;Web 框架规范)。任一端 Dev 实施不依赖另一端先完成。

**核心原则 — 视觉 vs 实现分离**:

| 维度 | 多端关系 | 来源 |
|---|---|---|
| 视觉契约(尺寸/圆角/fill/stroke/icon)| **必一致** | design-truth |
| 实现路径(API / 容器 / 渲染策略)| **不强制一致**,各按本平台规范 | iOS Apple HIG;Android Material Design;Web 框架 |
| 行为契约(交互/状态/数据回传) | **必一致** | PRD §x.y |

| 场景 | iOS(Apple HIG / SwiftUI)| Android(Material Design / Jetpack)|
|---|---|---|
| 列表 inline expansion | ForEach / List 内 `if let` 紧贴插入 / `DisclosureGroup` | RecyclerView 单 ViewType + VH 内嵌 + bind 切 drawable 拆顶/底圆角 + margin=0 + 共享 stroke |
| modal / 浮层 | `.sheet/.fullScreenCover/ZStack` | BottomSheet/DialogFragment/PopupWindow/inline |
| 圆角图片 | `.clipShape(RoundedRectangle)` | `ShapeableImageView` / Coil transformation;禁普通 ImageView |
| 渐变 stroke | `.overlay(stroke: LinearGradient)` | 无原生 API → 自定义 FrameLayout dispatchDraw + Shader |

**判定线**:涉及上述场景但 `grep -E "iOS 实现路径|Android 实现路径|HIG|Material Design"` 0 命中 = §3 sub-rule 违规。

---

## §4 task md 模型字段(强制)

### 头部模板

```markdown
- 身份:Dev A(`git as-a`) ← Android;Dev B(`git as-a`) ← iOS
- 分支:`dev/dev-a/...` 或 `dev/dev-b/...`
- capability_tier:**balanced**
- 工时:~Nh
```

### capability_tier 三选一（宿主无关）

- **`balanced`(默认 80%+ 任务)**:视觉对齐 / token 改 / 中等改造 / pendingAction / Toggle 复用 / 全屏选择页等
- **`deep`(7 大触发,任一命中即标)**:
  1. 架构妥协 / Option C / 跨 Feature 大重构 / 多 stage wizard 整合
  2. 高频手势多防(WaveformTrim 类)
  3. 复杂 bug 根因诊断(需最高档推理 + 多文件交叉)
  4. 多 stage / wizard / 跨页串联工作流
  5. **抽象 / 复用 / 举一反三决策**:抽公共控件 / base class / scaffold 升级 / 跨页规律抽象判断
  6. **框架已知 bug / 兼容性诊断**:SwiftUI / Asset Catalog / 平台 beta 已知坑,必须深度档 + WebSearch 实证
  7. **视觉契约切换 / 跨 Feature 状态广播架构**:视觉契约修改必各端同步 sweep;登录态 / token 变化广播给所有持字段的子 feature
- **`light`**:一行修复 / 翻译补全 / 单 drawable / 简单 grep + commit

协调端本身保持 `deep` 能力档；具体模型由当前宿主决定。

### 协调端自检 8 问(标 model 前问自己)

- Q1 涉及"抽公共控件 / 升 scaffold / 跨页复用"?是 → `deep`
- Q2 同模式跨 ≥2 task 重复出现(圆角图片 / gradient stroke / sheet 容器 等)?是 → `deep` + 加"复用思考"段
- Q3 涉及多 stage 串联 / 跨 Feature 数据流?是 → `deep`
- Q4 是高频手势 / 复杂状态机?是 → `deep`
- **Q5 涉及框架已知 bug / SwiftUI / Asset Catalog / 平台 beta 兼容性?**是 → `deep` + Step 4 WebSearch 实证
- **Q6 涉及视觉契约切换 / 跨 Feature 状态广播架构?**是 → `deep`
- Q7 都不是 → `balanced` OK
- **Q8 task 涉及 onAppear / onViewCreated / onCreate + 批量渲染(列表绑定 / 媒体初始化)?**是 → task md 必含"时序约束"段

### 误判兜底

当前档位跑卡 / fail / 复用决策不主动 → Dev 在 handoff 显式声明"建议升级能力档重试",协调端下次派单改标 `capability_tier: deep`。

---

## §5 视觉对齐任务强制证据机制

写"视觉对齐 / 多 sub-page / 多 stage / 还原设计稿"类 task md,任务书强制要求(缺一不合格):

### a. 节点对照表升级为属性对照

每节点列**关键属性 ≥ 3 项**(cr / fill / stroke / 字号 / 字重 / padding / 文案 / aspectRatio):

```markdown
| design-truth 节点 | 关键属性 | 实施值 | 状态 |
|---|---|---|---|
| stepFooter | h=68 / fill=#FFFFFF08 / Text "Step %d of %d" 16/500 / 10 bar | line N | ✅ |
| resultsPanel | cr=16 / fill=#FFFFFF08 / stroke=1pt #3F3F46 | line N | ✅ |
```

不只列节点名,**必须列具体属性值**。

### b. Read design-truth/{pageId}.png 必读

任务书强制 Dev **实施前 + handoff 写完前各 Read 一次 .png**:
- 实施前:把握整页视觉(找易漏的边框 / 间距 / 文字)
- 写 handoff 前:多模态视觉对比 + 主动列偏差

### c. handoff 含"非 design-truth 元素自审"段

```markdown
## 非 design-truth 元素自审
- 删除:SAVE TO LIBRARY(原因:不在 design-truth,无产品决策依据)
- 保留:close X 按钮(原因:产品决策,handoff 内显式声明)
- 新增:N/A
```

任何 Dev 自加 / 修改 / 移除的元素必须显式列 + 决策依据。

### d. 动态尺寸强制

cover / image / 大块占位 尺寸必须 **aspectRatio**(基于 design-truth w:h 真值),禁固定 dp:
- ❌ `layout_height="320dp"` / `.frame(height: 320)`
- ✅ `layout_constraintDimensionRatio="402:558"` / `.aspectRatio(402/558)`

### e. 协调端任务书自检

写 Stage 模板代码块前,**先 grep design-truth 真值的所有关键元素**(Text label / stroke / padding / aspectRatio),代码块必须含全 — 不能漏写关键元素让 Dev 严格按字面跑就漏(footer 漏 "Step N of 10" Text 历史教训)。

### f. 判定线

handoff 任一缺失即不合格:
- 节点对照表无属性列(只列节点名)
- "非 design-truth 元素自审"段缺失
- 固定 dp / wrap_content 高度(应 aspectRatio)
- "与 design-truth.png 视觉差异自述"段缺失

### g. 协调端登记反模式后必 sweep + 自检

登记新反模式 / 加新强制规则后,协调端必跑 3 步(防自身违规):

1. 立即 sweep active task md 检查全 fleet 是否符合新规则:
   ```bash
   for f in <frontend>/.ai-workspace/tasks/*.md; do
     # grep §X 关键标志(Read design-truth.png / 属性对照 / 非 design-truth 自审 等)
   done
   ```
2. 分类处理违规 task:
   - 已派未跑 → 立即 update task md
   - 已跑过 → 加 POST-HOC 警告头 + 必要时派事后修复 task
   - 成功跑且用户验收 OK → 不动
3. 写新 task md 前 checklist:全部视觉对齐反模式自检

**判定线**:登记反模式不 sweep + 同时写新 task 又违反同条 = 自我违规。

---

## §6 handoff escalation → coordinator-todos 自动转入(强制)

每次 Dev handoff 收到:
1. Read handoff §6/§7 escalation 段(必读)
2. grep "未做 / 后续 / 候选 / 待 / TODO / 暂不动 / 后续 task" 命中即转入 `<docs-hub>/.ai-workspace/coordinator-todos.md`
3. 加优先级标(P0/P1/P2)+ 来源 + 触发条件
4. **不清不撤** — 直到派 task md 完工(标 [x] 不删)

**写新 task md 前必扫 `coordinator-todos.md`**(防同源问题漏 sweep)。

---

## §7 决策后必 sweep 历史 + 写决策日志(强制)

每次决策"按 X 而非 Y"(PRD vs design-truth 冲突 / 用户实时反馈覆盖之前决策 / 框架行为修正等):

1. 写到 `<docs-hub>/.ai-workspace/decision-log.md` 含 5 项:冲突 / 决策 / 依据 / 历史 / sweep 触发 / 关联 task
2. 同步 sweep 历史:之前按 Y 实施的代码 / 反过来按 X 加的元素 — 必扫一遍
3. sweep 触发 = 转入 `coordinator-todos.md` 待办

**典型复发实例**:
- 按 PRD 加某元素 → 后按 design-truth(UI)删 — 漏 sweep "其他 PRD-only 元素"
- 白色 50% dimmer → 黑色毛玻璃 — design-truth 待更新

---

## §8 派单短指令格式(强制)

协调端必须 invoke `$dispatch-task`，确认**目标执行 session**的宿主；普通 Codex 派单不查询模型或推理档，
再运行稳定 `model-dispatch` launcher。把 stdout 原样放进“给 Dev 发送”；禁止凭记忆手写或
从本文其他宿主示例复制。机器装了 Claude Code/Codex 两种 CLI 不是当前宿主证据；宿主不明确
时停止并要求显式选择。

```bash
SULDE_MODEL_DISPATCH="${SULDE_HOME:-$HOME/.sulde}/bin/model-dispatch"
"$SULDE_MODEL_DISPATCH" --provider <claude|codex> \
  --tier <light|balanced|deep> --task .ai-workspace/tasks/{date}-{slug}.md \
  [--model-advice] # 仅用户明确要求模型建议时添加
```

- Claude Code 输出只能含 Claude 原生模型控制和 `/assign`；
- Codex 默认只输出任务正文；仅用户明确要求模型建议时才可输出 `/model`、`/reasoning`，禁止 Claude 型号、
  thinking 词、`/mode`、`/assign`、`/clear`、`ralph-loop`；
- “继续原任务/返修”不加 `--fresh-session`，保留当前上下文；
- 多任务逐项给出任务正文，不在一段里手工切换型号；
- 默认保留当前配置，不展示“无需切换”提示；旧模板示例不得覆盖此规则。

### 派单完成后的模型状态

不切换模型。只有用户明确要求建议时，才依据目标宿主和能力档生成建议。

### 长任务语言漂移防护

Agent 跑长 task 易出现"语言漂移"(中英混合 / handoff 段标题英化)。

**协调端**写 task md:
- 不夹杂英文段标题(`## Implementation` 改 `## 实施`)
- handoff 段名也用中文(`### 改动文件清单` 不是 `### Files Changed`)
- 如果 Dev 上次 handoff 已漂移英文,新 task md 加显式约束:`> ⚠️ handoff 段标题中文(避免语言漂移)`

### 反例

❌ 错误派单:未识别目标宿主就套 Claude 的 mode/model 与 assign 指令，导致 Codex session
收到无效或错误的宿主命令。

✅ 正确派单:
```
provider=codex,current_model=<实值>,capability_tier=deep → 按 Codex 路径渲染
```

---

## §9 Claude Code 大型 task 可用 ralph-loop 自循环

**宿主边界**:`ralph-loop` 是 Claude Code 工作流。目标 session 为 Codex 时不得输出本节命令；
使用当前 Codex 的原生持续执行/自动化能力或由受控 `agent-runtime.py` 执行。

**适用场景**:目标为 Claude Code 且 task md 含多项重复机械工作(audit 80+ 项 / 批量翻译 / 多 stage Wizard 同步实施 等),单轮跑不完 → 用 `ralph-loop` 自循环推进直到完成。

**机制**:`ralph-loop` plugin 装 Stop hook 拦截 session 退出,把原 PROMPT 反复喂给 Claude,Claude 看自己之前的 handoff / commit 继续推进,直到匹配 `--completion-promise` 或 `--max-iterations`。

### 派单格式(替代 §8 三行)

```
/clear
/model sonnet
/ralph-loop <PROMPT> --completion-promise "<PROMISE>" --max-iterations <N>
```

### PROMPT 设计铁律(写 ralph PROMPT 的 5 条)

1. **PROMPT 必须可重入**:Claude 每轮看同样的 PROMPT,要能"识别当前进度 + 继续",不是"重启"。**禁用** `/assign` 嵌套(每轮会重读 task md 浪费 token)。让 PROMPT 自包含"Read task md + Read 已有 handoff + 推进未完项"。
2. **completion-promise 文本严格**:用业务专属词(`IOS_AUDIT_COMPLETE` / `ANDROID_TRANSLATION_DONE`)而非通用词(`DONE`),避免 Claude 撒谎逃逸
3. **max-iterations 必设**:audit 类 30,翻译类 20,Wizard 类 50。**禁** `--max-iterations 0`(无限循环爆 token)
4. **handoff 路径明确**:PROMPT 内写明 handoff 路径,Claude 每轮 Read 检查进度
5. **完成判定可 verify**:用 grep 可验证的条件(如"handoff 含 80 行 + 自检 8 问全 ✅")而非模糊的"差不多了"

### 派单模板

```
/clear
/model sonnet
/ralph-loop 推进 <端> <任务名>。先 Read task md `.ai-workspace/tasks/<date>-<slug>.md` 拿 contract:按 frontmatter 切分支 + git 身份 + 思考模式。然后 Read 已存在 handoff `.ai-workspace/handoff/<date>-<slug>-result.md`(若存在),identify 还缺哪些项 + 自检 X 问哪几条未 ✅。继续推进未完项。全部齐全 → 输出 <promise>BUSINESS_SPECIFIC_PROMISE</promise>。 --completion-promise "BUSINESS_SPECIFIC_PROMISE" --max-iterations 30
```

### 监控动作(由 Agent 执行)

```bash
# 实时看 iteration 数
watch -n 5 'grep "^iteration:" <PROJECT_ROOT>/<frontend>/.claude/ralph-loop.local.md'

# 中途停止:在 Dev session 内输入 /cancel-ralph
```

Agent 负责执行监控与停止动作并汇报状态；上面的命令是执行器参考，不得作为用户代跑步骤输出。

### 何时**不用** ralph-loop

| 场景 | 用 ralph? |
|---|---|
| audit 80+ 项 / 批量翻译 100+ 文件 | ✅ 用 |
| 单 bug fix | ❌ 不用(单轮搞定 + /assign 已够)|
| UI 还原单页 | ❌ 不用 |
| 多 stage Wizard 整合(全部 stage 同 ViewModel 修)| ✅ 用(但需 `deep`,因有架构决策)|
| 性能 fix(需诊断 → 改 → 验证 → 改)| ❌ 不用(诊断 + fix + verify 都不可重入)|

### 反例(踩过的坑)

❌ ralph PROMPT 含 `/assign`:每轮 Claude 触发 /assign skill → 重读 task md + 重启流程 → 浪费 token
❌ promise 用 `DONE`:Claude 跑卡时输出 `<promise>DONE</promise>` 撒谎逃逸
❌ `--max-iterations 0`:无限循环,session 失控
❌ PROMPT 缺 handoff 路径:Claude 每轮不知道"进度在哪",可能重复跑同样项
❌ 完成判定模糊("跑完所有"):Claude 自我判定"差不多了"逃逸

### 与 /assign 选择决策

| Task md 类型 | 推荐 |
|---|---|
| 单一明确任务(fix / feature / refactor) | `/assign` |
| 多项重复机械工作(audit / 批量改) | `ralph-loop`(不嵌 /assign) |
| 复合任务(部分 fix + 部分 audit) | task md 拆开,各自匹配 |

---

## 附录:反模式索引(出现频次 ≥ 2 的,通用化)

| 反模式形态 | hook | 详 ADR |
|---|---|---|
| 视觉对齐强制证据缺(节点属性对照 / 非 design-truth 自审 / aspectRatio)| 视觉还原 task | `<docs-hub>/ADR/visual-alignment-evidence.md` |
| 协调端凭印象不查代码 | 起草 task md | `<docs-hub>/ADR/coordinator-impression-based-dispatch.md` |
| 单维度数据源 → 真数据返工 | 3 维同步 | `<docs-hub>/ADR/single-source-truth.md` |
| 设计稿不导 .png 凭文字猜形态 | UI task | `<docs-hub>/ADR/design-source-not-export-png.md` |
| task md 给 boilerplate 失去抽象判断 | contract-based | `<docs-hub>/ADR/task-md-boilerplate.md` |
| Dev session 旧 system-reminder 注入快照不更新 | 派单 /clear | `<docs-hub>/ADR/stale-system-reminder.md` |
| 协调端凭印象不查技术真值(平台官方文档 / framework) | Step 4 WebSearch | `<docs-hub>/ADR/coordinator-impression-tech-truth.md` |
| task md 缺 UI 时序约束(多端进场动画 jank)| Step 5b 时序约束 | `<docs-hub>/ADR/missing-timing-constraint.md` |
| 协调端忘记派发过的任务 | Step 0 baseline | `<docs-hub>/ADR/coordinator-forgot-dispatched.md` |
