---
doc_id: "ap-0134"
container: anti-patterns
platform: none
summary: "0134 协调端 pen-truth 批量铺设时未做 PRD↔设计稿反向校验"
---

# 0134 协调端 pen-truth 批量铺设时未做 PRD↔设计稿反向校验

- **平台**:协调端
- **复发次数**:0

## ❌ 错误

协调端用 Pencil MCP 批量铺 `pen-truth/{pageId}.md`(从设计稿提取节点 / 视觉真值)时,**只做 设计稿 → pen-truth 正向提取**,未做 **PRD → 设计稿 反向校验**(verify PRD 要求的所有 UI 元素是否在设计稿真实存在)。

后果:PRD 要求的元素 X 实际**设计稿真无**(设计师漏画 / 历史遗留)→ pen-truth 正向提取也无 X(正向无问题)→ 协调端起 task md 让 Dev 实施 X → Dev 凭印象 / PRD 文字描述自造视觉 → 双端不一致 / 视觉漂移。

实证链:PRD 要求某模式切换器 + 后端字段已建,但设计稿节点树根本无该控件;pen-truth 正向提取忠实于设计稿也无 → 不是 pen-truth 漏,是**设计稿漏**。若铺 pen-truth 时同步做反向校验,早就发现设计稿缺 → escalate 补设计 OR 改 PRD,避免该 BUG 进入实施排期。

## 为什么错

只做单向(设计稿 → pen-truth)正向校验,凭设计稿节点确认就当 pen-truth 真值齐,忽略 PRD 反向。

## ✅ 正确

pen-truth 铺设加 PRD↔设计稿反向校验 step:

```markdown
1. 正向提取(已有):Pencil MCP batch_get 拿设计稿节点 → 写 pen-truth/{pageId}.md
2. 反向校验(新加):
   - 列 PRD 该页所有 UI 元素要求
   - 对照设计稿节点逐项 verify
   - "PRD 要求但设计稿无" → 标 §警告 + escalate UX/PM
3. 三方校验:PRD ↔ 设计稿 ↔ API 字段必同步;若 API 已建但设计稿+pen-truth 漏 → 优先级 ⬆️ escalate

判定线(违一即 pen-truth 不签发):
- ❌ 只做正向提取(不查 PRD)
- ❌ 凭设计稿节点确认 = pen-truth 真值齐(忽略 PRD 反向)
- ✅ 三方对照 + 缺漏标 §警告 + escalate UX/PM
```

历史 backlog 复审建议:所有批量铺的 pen-truth 都该回溯反向校验,避免类似隐性 BLOCKED 累积。

## lint 状态

❓ 中等(pen-truth 文档格式 lint)— soft 警告:协调端新增 pen-truth/*.md 提交时,无 §警告 段 + 无 PRD 引用 → 警告未做反向校验。

## 关联

- 凭印象下发 task md(同源 master)
- audit subagent 凭关键词非 diff verify(同源:数据源单向校验,未反向 verify)
