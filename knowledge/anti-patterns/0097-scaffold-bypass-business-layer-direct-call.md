---
doc_id: "ap-0097"
container: anti-patterns
platform: harmonyos
summary: "scaffold 已建但业务层散落直接调底层 API → 视觉 / 行为不一致 + 跨期复发"
---

# 0097 — scaffold 已建但业务层散落直接调底层 API → 视觉 / 行为不一致 + 跨期复发

- **平台**:双端通用 + HarmonyOS（以及任何"scaffold 层 + Feature 层"分层架构项目）
- **复发次数**:4（+ 多次预警）
- **lint 状态**:⏳ pending（单类型 lint 已落地，通用 scaffold-bypass lint 框架待建）

## 现象

scaffold 层已定义某个组件（如 ConfirmDialog / AppTopBar / AdaptiveStateView 等），且 scaffold 顶部注释明示"业务层禁止直接使用 MaterialAlertDialogBuilder / AlertDialog.Builder / .alert 等底层 API，由 lint 规则扫描拦截"。

**但实际**:
- 业务层多个 Feature module 仍直接调底层 API，不走 scaffold
- lint 规则要么没生效 / 要么覆盖范围不全（如只扫 `feature-*` 没扫 `core-ui/src/main`）
- 业务视觉因此不一致（scaffold 是暗主题，业务层是 Material Default 浅色 → 用户感受弹窗时浅时暗，体验割裂）

**最关键的复发特征**:scaffold 抽出来后，**短期内 lint + code review 都能拦住**;但跨 1 个月以上 / 跨 Phase 后，新 Feature 开发的 Dev 不熟悉历史约定，**新写代码时直接用底层 API**，lint 规则若未持续扩展则放过 → 业务层散落数量持续累积（实证某次跨期达 5 个月）。

## 根因

| 原因 | 说明 |
|---|---|
| 1 | scaffold 抽出时**只在 scaffold 本体注释 "业务层禁止"**，没在 CLAUDE.md / shared-rules 反复强调 — Dev 写新 Feature 时不会主动查 scaffold 注释 |
| 2 | lint 规则**初版覆盖范围有限**，后续新加 Feature 落在未覆盖区域 → lint 不报 |
| 3 | lint 规则**仅扫单一 ALLOWLIST 文件名**，scaffold 类型多了需要 N 条 lint 规则，运维成本高 |
| 4 | code review **不强制 grep scaffold-bypass** |
| 5 | **scaffold API 不够易用**（如同步 fire-and-forget API 不如底层流式 API 顺手）→ Dev 偏向底层 API |
| 6 | **复发跨期长** = 团队记忆衰减规律，知识沉淀失效 |

## 损失

- 业务视觉不一致（暗 / 浅主题混杂）→ 用户体验割裂
- 每次发现后需要**周期性"业务层迁移 task"** — 工时持续消耗
- scaffold 抽出的初衷（"一次抽出，各处复用"）被打破 → 不如不抽
- lint 规则 ALLOWLIST 持续膨胀 → 维护成本上升

## 防护建议

### 短期

1. **scaffold 抽出后立即跑 lint 全量扫**:不只扫 `feature-*`，扫所有源码（排除 scaffold 层 + 测试目录）
2. **lint 规则参数化**:不写"008-confirm-dialog.sh / 009-app-top-bar.sh / ..." 多条，改成**一条 `scaffold-bypass.sh` 通用规则** + scaffold 清单 yaml 配置文件（列出"禁用 API + ALLOWLIST"映射）
3. **pre-commit hook 跑 scaffold-bypass.sh**:不只 CI，本地 commit 也拦
4. **scaffold 抽出 task md 强制段**:必含"业务层 grep 命中清单 + 全部迁完 + lint 规则就位 + ALLOWLIST 限制"4 项

### 中期

5. **scaffold API 必须比底层 API 更易用**:抽出时验证"用 scaffold API vs 底层 API 写 caller"代码行数，前者必须 ≤ 后者，否则 Dev 不会主动用 scaffold
6. **scaffold 抽出文档必含"业务层迁移完整清单 + 完成度"**:记 N/N 进度（0/11 → 7/11 → 11/11），新 Feature 开发前必读

### 长期

7. **季度 scaffold 体检**:每季度跑 `scaffold-bypass.sh` 全量扫，任何新增违规点立即派 task 迁回
8. **新 Feature 开发 checklist**:Dev 开新 Feature 前必看脚手架规范核心 scaffold 清单，写代码时主动找对应 scaffold 而非底层 API
9. **协调端周期 audit**:协调端定期 grep 全代码库底层 API 命中，若有未在 ALLOWLIST 文件，立即派迁移 task

## lint 候选规则草稿

```bash
# 通用版 scaffold-bypass.sh
# 读取 scaffold-map.yaml 配置文件:
#   scaffolds:
#     ConfirmDialog:
#       forbidden_apis: [MaterialAlertDialogBuilder, AlertDialog.Builder]
#       allowlist_files: [ConfirmDialog.kt, ...]
#     AppTopBar:
#       forbidden_apis: [Toolbar, ActionBar]
#       allowlist_files: [AppTopBar.kt]
# 扫:src/main/**/*.{kt,swift}（排除 scaffold 本体路径）
# 命中 forbidden_apis 且文件不在 allowlist = 违规
```

## 亚型:scaffold 已抽业务层不复用，但因视觉特殊

某页有特殊视觉装饰（如 radial glow + 大居中标题），简单替换 scaffold 会改设计视觉契约。Dev handoff escalate，协调端**接受现状**（不强改），登记为"scaffold 已抽业务层不复用，但因视觉特殊"亚型;后续 scaffold 改造时，若 scaffold 支持视觉装饰扩展 slot（如 `decorationSlot` + `bigCenterTitle` mode），再迁。

## 亚型:绕过 canonical helper/service 而非 UI scaffold（同根因,危害升级）

被绕过的不止 UI 弹窗/顶栏 scaffold,还包括**权威状态 helper / 收口 service**(如"是否 VIP"守卫、toast 封装、日期/价格工具)。业务层不调 canonical helper,而是内联复制判定逻辑或另读一份缓存。此亚型危害比 UI 不一致更重,分两支:

### (a) 双真值源静默 bug 地雷

绕过 canonical helper 时,业务层常顺手另建**第二份缓存 / 状态源**读同一个逻辑标志(典型:某开关既由内存对象字段 `flag > 0` 内联判定,又有一套读持久化 key `AppFlag` 判定 → **同一标志两套真值源**)。两源在多数路径巧合一致,但某条路径读到不一致值时**出 bug 且无 error 抛出**——纯静默漂移,排查成本极高。凡发现"绕过 canonical helper + 另起缓存"必列**最高优先级**收口:统一到单一真值源 helper(`isVip()` / `requireX()`),删掉所有内联判定与旁路缓存 key(死 key 也一并删,防未来误用重演同款静默 bug)。

### (b) task md 必给 canonical 件 file:line 复用蓝图

复发根因之一:协调端派 UI/重构 task md 的"复用思考段"只写**原则**("优先复用公共件"),没具体列"本页要用的弹窗/空态/守卫,canonical 件 = X(file:line);本页绕过点 = Y"。Dev 拿到只有原则的 task md → 各自现查现写 → 漏查既有件 → 重造(逐页单 session 交付时,"别人已写过同款"不在本 session 视野内,尤其明显)。

**修法**:task md 复用段必给"**canonical 件 file:line ↔ 本页绕过点**"对照表,Dev 拿 task md = 拿替换蓝图,不再现查现推。分批派治理、禁大爆炸 PR:已有件机械替换一批(低抽象);新抽/合并公共件一批(有抽象判断);纯样板高 churn(裸 toast、硬编码色值)独立 sweep,待在途分支 merge 后再扫。

## 关联

- 协调端 audit 跳 grep 接口契约（类似根因 — scaffold 真值没在 audit 流程内被引用）
