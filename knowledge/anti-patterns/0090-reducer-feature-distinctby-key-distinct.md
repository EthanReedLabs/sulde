---
doc_id: "ap-0090"
container: anti-patterns
platform: none
summary: "Reducer / Feature 内 `distinctBy` 改 key 不实测 distinct 数量"
---

# 0090 — Reducer / Feature 内 `distinctBy` 改 key 不实测 distinct 数量

- **平台**:双端通用
- **复发次数**:1
- **lint 状态**:⏳ TODO（grep `distinctBy` 在 Reducer / Feature reducer / mergeState 内，要求附近含"实测 distinct .* N 个"注释）

## 现象

Dev 在 Reducer / Feature mergeState 内改 collection `distinctBy` 函数的 key 时，不实测新 key 下 distinct 数量，导致下游 UI 渲染元素数量爆炸（几倍 / 几十倍 / 几百倍），引入主线程 inflate 卡顿。

典型案例:后端某接口返大量原始行
- 改前:`distinctBy { labelName }` → distinct ~14-16（对应设计 4 个 chip 量级）
- 改后:`distinctBy { typeId }` → distinct **524**
- 下游:HorizontalScrollView `removeAllViews()` + `addView(TextView) × 524` 主线程同步 inflate ~1100ms = 卡 1 秒（实测某次修复 firstFrame 1440ms → 188ms 降 87%）

## 根因

1. Dev 改 key 时只看"按 spec 应以 typeId 为主"语义对齐，**没意识到 distinct 数量 = UI 元素数量**
2. 原代码可能有防御注释（如"避免 inflate 700+ TextView 主线程卡 1.7s"），但**改的时候顺手删了**
3. 测试时数据可能少量（几条 mock），distinct 数量看不出爆炸;真实后端数据返回时才暴露
4. 协调端文档凭印象 — 没在 PR review / commit message 写"实测 distinct N 个 vs M 个"

## 修法

Dev 改 distinctBy key 时必跑 3 步:

1. **实测新 key distinct 数量** — `Log.d("X", "distinct=${list.distinctBy{newKey}.size}")`
2. **若数量比改前 ≥ 3 倍**:STOP，handoff 协调端 — distinct 数量增加意味着下游 UI 元素增加，可能引入卡顿
3. **若保留原 key 必要**:**保留防御注释**（原注释必须保留 + 更新原因）+ 同步加 lint 规则

## 反例

```kotlin
// ❌ 危险 — 不实测 distinct 数量，直接改 key
- state.copy(labels = intent.labels.distinctBy { it.labelName }, ...)
+ state.copy(labels = intent.labels.distinctBy { it.typeId }, ...)
//                                   ^^^^^^^^^^^^^^ key 改了，但 distinct 数量从 ~14 跳到 524!
```

```kotlin
// ✅ 正确 — 保留防御注释 + 实测注释
// 防御性去重:backend 返回关联表全部行（实测 778 条 / 524 distinct typeId）。
// 按 labelName 去重:实测 distinct labelName ~10-30 个，与设计（4 个 chip）量级一致，
// 避免 HorizontalScrollView 内 inflate 500+ TextView 主线程卡 1+s。
state.copy(labels = intent.labels.distinctBy { it.labelName }, ...)
```

## lint 规则草稿

```bash
#!/bin/bash
# rules/00X-reducer-distinctby-must-have-count-comment.sh
# 检测:Reducer / Feature 内 distinctBy 改动必须附近含"实测 distinct .* N 个"注释

set +e
violations=0

for f in $(grep -rln "distinctBy" <feature 源码目录>/ 2>/dev/null; \
            grep -rln "distinctBy" Sources/Feature*/ 2>/dev/null); do
    context=$(grep -B 5 -A 1 "distinctBy" "$f" 2>/dev/null)
    if ! echo "$context" | grep -qE "实测.*distinct|distinct.*个|distinct=.*[0-9]+|数量.*≥"; then
        echo "[lint:00X] $f 内 distinctBy 缺实测 distinct 数量注释"
        violations=$((violations+1))
    fi
done

exit $violations
```

## 关联

- 协调端文档凭印象 — Dev 改代码删防御注释是其子症状
- UI 时序约束 — inflate 524 TextView 阻塞进场动画
