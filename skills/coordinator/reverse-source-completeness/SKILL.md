---
name: reverse-source-completeness
description: 协调端反抽源真值端(source-of-truth stack,如 Flutter)写 design-truth / api-contract / task md 前,跑完 14 步保障反抽完整性,杜绝 grep 浅采 / 凭印象 / 漏 cross-context 等 5 类反模式。当用户说"反抽 X 页面 / 看源端怎么做 / 写 design-truth / 派 UI 还原 task / SSE / endpoint 反抽"等触发词必 invoke。覆盖 3 阶段(静态深抽 / 动态实证 / 流程沉淀)+ 14 步 + 量化指标 gate + self-check 5 问。
user-invocable: true
---

# 协调端反抽源真值端完整性 14 步 protocol

> **适用**:协调端把一套「源真值端」(source-of-truth stack,如 Flutter / 既有 Web / 参考 App)反抽成 design-truth / api-contract,再派给「目标端」Dev(如 HarmonyOS / 新平台原生)实施的工作模型。下文以 Flutter → HarmonyOS 为跑通示例,占位符 `<source-repo>` = 源真值端工程,`<target>` = 目标端。
>
> **生成动机**:某次复杂 dialog 反抽 3 轮返工(每轮发现 5-7 项 drift),用户反问"是不是反抽流程有结构性问题"。以 zoom-out 视角 + systematic-debugging retrospective 沉淀本 SKILL。
>
> **关联**:
> - 上游:反抽必读源码原则(本 SKILL 升级到"读得完整深")
> - 下游:反模式 0142 多轮返工(本 SKILL 是其矫正机制)
> - 兄弟:writing-task-md(task md 起草前的反抽 input gate)/ multi-source-review(本 SKILL 调起的 two-pass review 工具)

---

## §0 触发场景(invoke 时机)

| 场景 | invoke |
|---|---|
| 写 `design-truth/{page-id}.md` 新增 / 大更新 | ✅ 必 |
| 写 `api-contract/{module}.md` 新增 endpoint | ✅ 必 |
| 起 UI 还原 / 视觉对齐 / SSE / 复杂 dialog / state 机 类 task md | ✅ 必 |
| 用户反馈"目标端 X 功能跟源端不一样" → 反向 audit | ✅ 必 |
| 一行修复 / pre-commit hook / 简单 grep 替换 | ❌ skip |

---

## §1 14 步 checklist(3 阶段)

### 阶段 A:静态深抽(基于代码,投入低收益高)

#### **A1. 全文件 Read 主入口(替 grep 浅采)**

```bash
# ❌ 反模式
grep "<SomeFooterBtn>" <source-repo>/lib/.../<some_dialog>.dart

# ✅ 正解
Read <source-repo>/lib/pages/<module>/view/<some_dialog>.dart   # 全文(数百行)
Read <source-repo>/lib/pages/<module>/view/<some_footer_btn>.dart  # 全文
# ...所有关联 source file 全 Read,不只 build() / 入口函数段
```

**Gate**:Read 行数 ≥ 文件总行数 70%(或全文)。

**收益**:某次反抽第 1 轮多项 drift(如 footer 列数错 / 某标志位实为 HARDCODED / 单选 vs 多选 / chip 高亮样式 / 末项分隔漏)大多可省——皆因当初只 grep 关键节点未通读。

#### **A2. 构造调用图(call graph)**

入口 → terminal,每节点 Read。示例:

```
某 Page CTA "<按钮文案>"       ← 入口
  └─ _showXxxDialog()          ← line NN(type mapping 常藏在此!)
      └─ Get.dialog(XxxDialog(...))
          └─ _requestXxx()     ← line NN(SSE / 主调)
              └─ HttpUtils.postStream()   ← http_utils.dart:NN
                  └─ DioManager.dio.post  ← dio_manager.dart(interceptor 链)
                      └─ RequestInterceptor.onRequest  ← request_interceptor.dart(token attach!)
```

**输出**:Mermaid sequence / 文字 tree → 贴入 design-truth §X "调用链"段。

**Gate**:树每节点必 Read(可能跨 5-10 文件)。

**收益**:某次反抽第 3 轮 type mapping 遗漏 100% 可省——因入口包装函数整段未 Read,导致 mapping 逻辑漏。

#### **A3. State machine 完整列**

所有 `@State` / `setState` / lifecycle hook + 每个 if/else / switch case + cross-state transition。

**输出表**:
```markdown
| state | init | 转移 trigger | UI 影响 |
|---|:-:|---|---|
| _isShowLoading | true | onData header 后无变 / onDone false | gif 显隐 |
| _isShowRole    | false | onDone true | header avatar+name 显隐 |
| _isShowFeedback | false | onDone true | footer 显隐 |
```

**Gate**:state 数 ≥ 真实数(常见 5-10);转移 trigger 写明 file:line。

#### **A4. Error path inventory**

所有 `catch / onError / Result.error / ToastUtil.showMsg / ret.msg ?? ''` → 错误态行为完整。

**输出表**:
```markdown
| 错误源 | 源端行为 | 目标端应施 |
|---|---|---|
| SSE onError | toast 报错,dialog 不关 | onError 同 toast + cover 不关 |
| feedback POST fail | toast ret.msg | ResultErr msg + toast |
| ...                                       |
```

**Gate**:每 endpoint + lifecycle 错误态必标 ≥ 1 行。

#### **A5. Resource inventory + smart selector sweep**

```bash
# 1. ls asset dir 全 list dark/light 配对
ls <source-repo>/assets/images/ | grep -iE "<keyword>"

# 2. grep 主题常量表 smart selector(runtime 主题切换)
grep -n "<asset_name>" <source-repo>/lib/common/<AssetConst>.dart

# 3. 对照 light + dark 真实文件数 vs Dev 已迁数
```

**输出**:
```markdown
| 元素 | light | dark | runtime selector | Dev 状态 |
|---|---|---|---|---|
| shading_background | ✅ | ✅ | AssetConst.dart:NN `if(isDarkMode)` | ⚠️ 待 verify |
```

**Gate**:asset 数 + smart selector 数 全 match;若 dark 缺 → 协调端反抽时必 flag。

**收益**:某次反抽第 2 轮 dark variant 遗漏 100% 可省。

#### **A6. Platform / 条件分支 grep**

```bash
grep -rn "isPad\|_brand\|isHuawei\|isDarkMode\|UniversalPlatform" <source-repo>/lib/.../<dir>
```

**输出**:列所有 conditional + Dev 端 handling(用户/设备/主题/locale 分支)。

**收益**:某次反抽第 1 轮 dropdown 品牌条件(某品牌 5 项 / 其他 4 项)100% 可省。

---

### 阶段 B:动态实证(基于真机/网络,投入中收益高)

#### **B1. 源端真机走端到端 e2e + 录像/分镜截图**

```
真机起源端 app → 走 task 涉及功能完整 flow,示例:
  1. 登录
  2. 首页 → 选 module → 某 Page → 交互 → 完成
  3. 完成页(主 CTA 截图)
  4. tap 主功能 → 主 dialog 截图(完成态 + streaming 态)
  5. ⋯ More → dropdown 截图
  6. dropdown 各项点击各子 dialog 截图(feedback / partner / report)
  7. 错误态触发(断网 / VIP gate / leftCount=0)各截图
```

**输出**:`docs-hub/source-reference/<tab>/<page>/{NN-<state>}.png`(≥ 6 张 / page)

**Gate**:每 visible state ≥ 1 张截图;design-truth 内 §X 必含截图 ref。

**收益**:某次反抽的 visual drift(CloseX 位置 / 横滑 vs 竖排 / chip Wrap / 装饰角 等)100% 可省。

#### **B2. 抓包源端真机流量(SSE / 复杂 endpoint)**

涉及流式 / cookie / 复杂 header / SSE / VIP gate 类 endpoint **必抓包**(Charles / Proxyman):

**输出**(贴入 api-contract):
```markdown
### endpoint POST /<module>/createResponse — 真请求 / 真响应

Request:
  URL: https://<host>/api/app/v1/<module>/createResponse?recordId=X&type=3
  Headers:
    token: <jwt-real-token>
    Accept: text/event-stream
    Cache-Control: no-cache
    Connection: keep-alive
    Content-Type: application/json
    lang: zh-CN

Response:
  HTTP/1.1 200 OK
  Content-Type: text/event-stream;charset=UTF-8

  data: {"type":"header","roleId":1,"roleName":"<角色名>","roleAvatar":"https://..."}\n\n
  data: {"type":"text","text":"嗨"}\n\n
  data: {"type":"text","text":",看到你的记录"}\n\n
  ...
  data: {"type":"footer","id":12345}\n\n
```

**Gate**:复杂 endpoint(SSE / 流式 / VIP-gated)必有真请求 + 真响应 sample。

#### **B3. Multi-device / theme / account cross-test**

- 设备 A vs 设备 B / dark vs light / VIP vs 非 VIP / 计数边界(0 / 1 / -1)
- 每 cross-test 截图存 `source-reference/<tab>/<page>/cross-<env>/`

**Gate**:platform variation grep(A6)命中的条件 → 必 cross-test。

#### **B4. 后端 swagger / 真响应 sample 抓**

不止 DTO 字段名,要真响应 sample(`late field` 实际真值 / 空缺值 fallback / null 处理)。

**Gate**:每 endpoint api-contract 含"真响应 sample"段(贴 5-20 行 JSON);不能只靠源端 `late field` DTO。

---

### 阶段 C:流程 / 工具(基于反模式累积,投入低长期收益高)

#### **C1. 反抽完整性 self-check 8 问(派单前必答)**

```markdown
1. 全文件 Read 比例 ≥ 70%? (A1 gate)
2. 调用图 5+ 节点完整 Read? (A2 gate)
3. State machine 5+ state + lifecycle 表 完整? (A3 gate)
4. Error path 表 ≥ N 行(N = endpoint 数)? (A4 gate)
5. Resource dark/light + smart selector sweep 完成? (A5 gate)
6. 真机 e2e 截图 ≥ 6 张? (B1 gate)
7. 复杂 endpoint 抓包真响应? (B2 gate)
8. Platform variation 条件分支 grep 完成? (A6 gate)
```

任一 No → **反抽不齐,禁起 task md**。

#### **C2. Spike-driven 不确定项 verify**

反抽完成后必标:
- 已 spike verified 的目标端限制 / 真值 list(如目标端 UI 框架的组件能力边界)
- 未 verified 的 unknown → 派 spike task 先 verify

**Gate**:task md `§AMENDMENTS` 段不含"待 spike verify"项 = 反抽 + verify 双闭环。

#### **C3. AMENDMENTS retrospective(每次 drift 发现后必反推)**

每次发现 drift → 反推哪步反抽方法漏了 → 该方法升级到本 SKILL checklist + 反模式沉淀。

**Gate**:每个 fix task md 完工后 ≥ 1 行 retrospective 写进反模式 / SKILL 升级。

#### **C4. Two-pass review(Explore subagent 双盲 sweep)**

Coordinator 反抽 → 派 Explore subagent 用**不同 keyword** 再 sweep 一遍 + 找 drift → 真值确认才派。

**Gate**:复杂 task(≥ 5 endpoint or ≥ 3 sub-dialog or SSE)必跑 two-pass。

---

## §2 量化指标 Gate(派单前 hook 验)

| 指标 | 反面(未走本 protocol 时) | Gate(本 SKILL 强约束) |
|---|---|---|
| 源端行 Read 数 / 文件总行数 | ~30% | **≥ 70%** |
| 截图覆盖 state 数 | 0-3 | **≥ 6**(每 visible state ≥ 1)|
| 调用图节点 Read | 部分 | **全节点(5-10)**|
| Endpoint 真响应抓包数 | 0 | **≥ 1 per complex endpoint** |
| State machine 表 | 缺 | **必含,转移 trigger 标 file:line** |
| Error path 表 | 缺 | **必含,每 endpoint ≥ 1 行** |
| Asset light/dark 对照 | 缺 | **必含 + smart selector sweep** |
| Platform variation 条件分支 | 缺 | **必含(grep isPad/_brand/Locale)** |
| Spike-verified 不确定项 | 部分 | **全目标端限制 spike 闭环** |
| Two-pass review(≥ 5 endpoint 或 SSE 类)| 缺 | **必跑** |

**Hook 拦截**(待 enable):若 task md 无下列段标 → 拒发:
- §调用图 / §state machine / §error paths / §asset & smart selector / §platform variations / §真请求 sample(复杂 endpoint)

---

## §3 反抽完整后输出模板

派 task md 时,coord 必同步更新 / 新建对应 design-truth + api-contract,**含以下段**:

```markdown
# {page-id} — 源端反抽真值 v{N}

## §0 入口 + 调用图(per A2)
[Mermaid sequence or tree,标每节点 file:line]

## §1 节点树(per A1 全 Read)
[完整 widget tree + 属性数值;每节点 ref file:line]

## §1.5 4 维真值清单(per UI 还原铁律)
| 维 | 源端 ref | 真值 |
| 节点 | file:line | ... |
| 数值 | file:line | ... |
| 资源 | file:line + ls assets | ... |
| 行为 | file:line | ... |

## §2 State machine(per A3)
[state 表 + 转移 trigger + UI 影响]

## §3 Error path(per A4)
[errors 表 + 目标端应施]

## §4 资源 inventory(per A5)
[light/dark 配对 + smart selector + asset dir ls]

## §5 平台 / 条件分支(per A6)
[isPad / _brand / isDarkMode / Locale grep 结果]

## §6 目标端可行性 verify(per C2)
[源端行为 vs 目标端路径 + spike 状态]

## §7 真机截图 baseline(per B1)
[≥ 6 截图 ref + 关键发现 vs §1]

## §8 真请求 / 真响应 sample(per B2,复杂 endpoint 必含)
[抓包数据]

## §9 反抽完整性 self-check(per C1 8 问全 ✅)
- [x] 全文件 Read ≥ 70%
- [x] 调用图全节点 Read
- ...

## §10 修订历史 + AMENDMENTS retrospective(per C3)
```

---

## §4 反模式禁区

- ❌ **grep 浅采替全文 Read**(本 SKILL 主反模式)
- ❌ **凭命名规律推测 endpoint / DTO 字段名**(per 反抽必读源码原则)
- ❌ **跳过真机 e2e 凭代码反抽视觉**(某次反抽 visual 多 drift 根因)
- ❌ **dark mode resource punt 给 follow-up**(反抽时未 sweep dark variant)
- ❌ **跳过 type / state mapping 函数 Read**(入口包装函数未通读致错位)
- ❌ **省略 cross-context architecture verify**(目标端跨上下文架构未验致运行期卡死)
- ❌ **缺 §AMENDMENTS retrospective**(drift 找到不沉淀)
- ❌ **缺 §真请求 sample 仅靠源端 DTO**(SSE chunk 实际格式不验)
- ❌ **single-pass review,不 two-pass**(复杂 task 必双盲)

---

## §5 Self-check 5 问 before dispatch

```
Q1: design-truth + api-contract 是否含全 §0-§9 段?
Q2: §量化指标 8 项 gate 全过?(70% Read / 6 截图 / 调用图全节点 / 1 真响应 / state 表 / error 表 / asset 对照 / platform variation)
Q3: §AMENDMENTS retrospective 是否已落反模式 / SKILL 升级?
Q4: 复杂 task 是否跑了 two-pass review(Explore subagent)?
Q5: 未确定的目标端框架限制是否已 spike verify 闭环?
```

任一 No → 反抽 / spike 不齐,**继续补,不 dispatch**(per 反模式 0142 多轮返工根治)。

---

## §6 关联

- 反抽必读源码原则:反抽不信推测,本 SKILL 升级到"读得完整深"
- 反模式 0142 多轮返工:本 SKILL 是其矫正机制
- writing-task-md:task md 起草前的 input gate
- multi-source-review:sibling skill,本 SKILL 调起的 two-pass review 工具

---

**版本**:v1.0(基于某复杂 dialog 3 轮反抽 retrospective + zoom-out + systematic-debugging 沉淀)
**累积来源**:某次多轮反抽 drift inventory / 用户反问"流程是否有结构性问题" / 协调端 zoom-out + systematic-debugging 复盘
