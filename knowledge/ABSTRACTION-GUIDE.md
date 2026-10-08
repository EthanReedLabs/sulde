# 沉淀抽象指南(Freebeat → sulde-cc 通用化)

> ⚠️ **本文降级为「首个来源项目(Freebeat)案例」历史存档**。项目无关的通用贡献标准以 [`SEDIMENTATION-STANDARD.md`](SEDIMENTATION-STANDARD.md) 为准;两者冲突时以 STANDARD 为准。后续所有来源项目照 STANDARD 做,本文仅供参考首个项目怎么抽象。
>
> 把 Freebeat 项目沉淀(反模式 / 技术文档 / 工作模型)抽象成**项目无关的通用版**,同步到 sulde-cc plugin。
> 双留:抽象结果同时写 `haifeng/_sulde-sync/`(Freebeat 留底)+ `ClaudePlugin/sulde-cc/knowledge/`。

## 语言
**中文**(对齐 sulde-cc 现有 skills/coordinator 的中文风格;docs/template 那层英文不在本次范围)。

## 保留(方法论通用词,**不删**)
协调端 / Dev / 甲方(=客户/需求方)/ 设计稿(.pen 概念)/ pen-truth(设计真值概念)/ task md / handoff / 敏感清单 / worktree / 完工三步 / scaffold / 三态视图 / MVI / TCA / Android / iOS / Pencil MCP / SSE / 真机验证 / baseline / 反模式编号。
→ 这些是 sulde-cc 已采用的方法论词汇(它现有 skills 也保留),属通用资产。

## 删(项目特有,**必删/改写**)
1. **项目名**:`Freebeat` / `freebeat-android` / `freebeat-ios` → 删或改"本项目 / Android 端 / iOS 端"。
2. **commit hash**:`8c308f0e` / `9eaf2e9` / `AND-29` 等编号 → 删(留"某次修复"即可)。
3. **具体类/文件路径**:`MvAgentActivity.kt` / `OnbeatEffectInputViewModel:177` → 改占位 `<某 Activity>` / `<某 ViewModel>` 或删行号。
4. **具体页 ID**:`03A1B` / `03D0` → 删或"某参数页 / 某状态页"。
5. **业务功能名**:MV Agent / Onbeat / Music Cover / pricing / 订阅 / 裁剪 / 分镜 / 片段 / credits / Used → 改通用("某创作流 / 某列表页 / 某操作面板")。
6. **人名 / 日期**:Chen Hao / Sun Yi / `dev/sunyi/xxx` / 2026-xx-xx → 删。
7. **内部文件引用**:`xxx-result.md` handoff / xlsx / 截图路径 / 具体 memory 文件名 → 删或泛化("某 handoff / 某验收表")。
8. **PRD/pen-truth 章节号**:`§6.5` / `pen-truth/03A1B.md` → 删具体号,留"PRD / 设计真值"概念。

## 改写示例
- "0625 r2 截图只画了 Add Music 未登录空态" → "某页空态截图(无列表项)"
- "MV 参数页标题" → "某参数页标题"
- "fa04fdf6 把 sticky 改成跟随" → "某次改动把 sticky 改成跟随滚动"

## 输出规则
- **同名同编号**(`0140-xxx.md` 仍叫 `0140`),便于与 Freebeat 原始追溯。
- 结构保留:`# 编号 标题` / `## ❌错误` / `## 为什么错` / `## ✅正确` / `## lint 状态` / 关联。
- 删掉"首次踩坑日期/来源 handoff"这类纯项目元数据行;保留"平台 / 复发次数 / lint 状态"。
- 代码示例:若是通用框架代码(SwiftUI/TCA/MVI)→ 保留,只把业务变量名改通用。

## 落点
| 类 | Freebeat 留底 | sulde-cc |
|---|---|---|
| 反模式 | `haifeng/_sulde-sync/anti-patterns/` | `knowledge/anti-patterns/` |
| 技术文档 | `haifeng/_sulde-sync/tech-docs/` | `knowledge/tech-docs/` |
| 工作模型 | `haifeng/_sulde-sync/work-model/` | diff `skills/` + `knowledge/work-model/` |
| 案例研究 | `haifeng/_sulde-sync/tech-docs/案例研究/` | `knowledge/tech-docs/案例研究/`（经 curate-to-kb 三道门：C 验真 / A 对齐标杆 / B 脱敏）|

> **案例研究类脱敏更严**：技术案例不使用方法论词汇（协调端 / task md / handoff 等），故按"全脱敏"处理——项目名 / 包名 / endpoint / CDN / commit / 人名 / § 全删，只留项目无关的工程内核 + 通用平台机制。区别于上面三类（保留方法论通用词）。新增 / 上浮走 `curate-to-kb` skill。
