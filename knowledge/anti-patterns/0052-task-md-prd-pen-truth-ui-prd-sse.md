---
doc_id: "ap-0052"
container: anti-patterns
platform: none
summary: "0052 协调端写 task md 凭单一数据源(只看 PRD 或 pen-truth 或接口),未做 UI/PRD/…"
---

# 0052 协调端写 task md 凭单一数据源(只看 PRD 或 pen-truth 或接口),未做 UI/PRD/接口 3 维交叉验证 → SSE 真数据来时字段对不上 → 返工

- **平台**:协调端(task md 写作类)
- **复发次数**:1(集中暴露)

## ❌ 错误 — 症状

协调端写 task md 时只对照单一数据源(典型:只看 PRD 文字规格 / 或只看 pen-truth UI 真值 / 或只看接口字段),没做 3 维交叉验证。Dev 按 task md 实施完毕,但当 SSE 真数据来时:

- view 字段渲染数据来源是 hardcoded mock(从未对接 SSE 真返回)
- 或 view 字段名 / 结构与接口 task_name 子字段不匹配
- 或 PRD 描述的字段在接口侧根本不存在

→ Dev 必须返工(可能涉及 Spec / Adapter / parser / State / view 全链路)

## 为什么错(根因)

某创作流实例:
- 协调端写 task md 时只对照 PRD 某节(单维度)
- 完工后用户问"阶段字段对照"→ audit 发现 pen-truth 阶段数 与 PRD 描述阶段数 冲突 — 第 2 维度才发现
- 用户进一步问"UI/UX/PRD/接口 3 点结合"→ 协调端再 audit 接口字段 比 PRD 描述更简 — 第 3 维度发现接口字段不一致
- → **3 维都不一致**,但都只单维度看,Dev 实施"对照 PRD" 然后实测时 SSE 真数据来才发现字段对不上

## ✅ 正确 — 修法

协调端写 task md / audit 反模式 / 修 bug 前**必做 UI/PRD/接口 3 维同步**(详 `shared-rules/data-sources.md`):

1. **UI 维**:Read pen-truth/{pageId}.md + .png + grep 节点属性
2. **PRD 维**:INDEX 找节 line N → Read offset/limit
3. **接口维**:API SPEC INDEX 找 endpoint 或 task_name → Read 字段 + 基础模型
4. **生成 3 维对照表**(每字段一行:UI ✅ / PRD line / 接口字段 / 双端实现 / 一致?)
5. **3 维冲突项**:
   - UI vs PRD 冲突 → 按 pen-truth
   - PRD vs 接口字段不匹配 → **协调端发邮件甲方解分歧**(异步)
   - 3 维都不一致无法自决 → **task md handoff 留 Dev verify + 反馈**

## 判定线

协调端 task md / audit 文档**必含"3 维对照表"段**:

```bash
grep -A 5 "UI(pen-truth)\|PRD line\|接口字段" .ai-workspace/tasks/*.md
# 缺 = 违规
```

## 防护加固(第 4 维 + view_render_mode)

协调端写 task md 前 **5 步审单**加:
- **Step 3.5 — grep 双端当前实施状态**(不只 pen-truth + PRD + 接口三维,还要 audit "当前代码实施" 第 4 维)
  - 复发实例:协调端凭 pen-truth 写 fixes,**没 grep 双端当前实施状态** → 一端已 100% 对齐 → no-op 关闭;另一端按 task 改了 — 双端不对称根因 = 协调端未 audit 当前实施

协调端给 "cp asset" 类 task md 必含 **`view_render_mode` 字段**:
- `brand-png-direct`(PNG 自含 brand bg + logo,直接 frame 显示)
- `lucide-bg-tint`(lucide icon + 彩色 Circle bg + .foregroundColor)
- `sf-symbol-fallback`(SF Symbol 占位,后续替换)
  - 复发实例:协调端给"cp 真彩 PNG 资源"但**未指定 View 渲染方式** → Dev cp 了真彩 PNG,但 View 仍用早期 SF Symbol 占位设计(彩色 Circle bg + `.foregroundColor(.white)` 强制 tint)→ **真彩 PNG 被染白渲染**

## lint 状态

- 协调端:✅ shared-rules `data-sources.md` 3 维同步铁律已加
- Android/iOS:⏳ TODO(协调端审计 task md grep "3 维对照"段)

## 关联

- shared-rules `data-sources.md` 3 维同步铁律
- 协调端凭印象 — 单维度凭印象 = 双重违规
- 网络 / 接口接通系列 — 都属于"接口维度盲区"反模式
