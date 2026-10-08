---
doc_id: "ap-0120"
container: anti-patterns
platform: none
summary: "协调端 API 文档多版本漏读 → 凭印象判 BE 阻塞"
---

# 0120 — 协调端 API 文档多版本漏读 → 凭印象判 BE 阻塞

- **平台**:协调端
- **复发次数**:0

> **触发**:user 反问"对方接口都上线了"才纠正。

## ❌ 错误

协调端 grep API 文档时只命中**单一版本**(如 v1 主文档),漏读同目录下的新版本文档(v2 / v3,文件名常带日期后缀),据此凭印象判"BE 没明文契约 → 阻塞",甚至忘了自己此前在内部真值文档(BTM)里已 cite 过新版本的 REST 链路。

### 失误链路(典型)

| 协调端动作 | 失误本质 |
|---|---|
| 写"等 BE 二选一" | 只读 API 文档 v1,凭抓包结论判 BE 阻塞 |
| grep `audio / merge / result_url` 全在 v1 主文件 | **漏读带版本后缀的 v2 文档** |
| 派 audit task md 以"抓 in-app vs download URL 对比"为方向 | 误传字面表象 + 没问 user 最新真值 |
| user 反馈"下载也不行",仍只 grep v1 → 答"无明文契约,BE 阻塞" | 凭印象推理 |
| user 反问"对方接口都上线了" | 才追到 v2 完整 REST 链路 |

## 真值

新版本 API 文档(带日期后缀)早已写明完整 REST 链路(多个 endpoint + 完整响应 schema + 优先级读取规则 + 状态枚举 + 流程图)。内部真值文档(协调端自己此前写的)也已 cite 该内容 — **协调端自己写的话自己后来忘了**。

## 为什么错

- API 文档目录下有**多版本文档共存**(v1 / v2 / v3 各代际),协调端不自动扫全部。
- v2 文件名带日期后缀,v1 没后缀,grep 默认 alphabetical 可能遗漏。
- 内部真值文档自身 cite v2 内容,但协调端 grep 时没 re-Read 完整段。
- **协调端凭印象**"我之前看过 API 文档" → 实际只看过 v1。
- **凭印象推理**"BE 没明文契约 → 阻塞" → 实际 v2 早写明 REST 链路。

## ✅ 正确

### 1. baseline grep 模板加多版本扫

```bash
# 写 task md / 起 BE 推单前 grep API 文档,必扫全部版本
ls 06_Api文档/ | grep -i "api\|spec"     # 列全文档清单,确认全部版本

grep -n "<keyword>" \
    06_Api文档/*SPEC_V*.md \
    06_Api文档/*agent-detail-api*.md \
    06_Api文档/*INDEX*.md
# 若命中多版本不同写法 → 多版本一致性 audit:协调端必决定以哪版为真值
```

### 2. 多版本不一致时的真值优先级

| 优先级 | 来源 | 说明 |
|:-:|---|---|
| 1 | **真实 prod 流量抓包**(Charles / curl / Web devtools)| 最强真值 |
| 2 | **最新版本文档**(v3 > v2 > v1)| 后写的覆盖先写的 |
| 3 | **带日期版本** vs 无日期 v1 | 日期版本明确替代 |
| 4 | **内部真值文档自己 cite 的真值** | 协调端自己实证沉淀的不能忘 |

### 3. user 反问触发自检

- 当 user 说"对方接口都上线了" / "Web 在用" / "已经有了" → **立即停止"BE 阻塞"叙事**,改为"我哪里漏读了"。
- 失误模式:协调端编"BE 没做 → 推单催办"故事 vs 真值"BE 早做了 → App 未 wire";前者甩责 BE,后者揽责自己。

### 4. 内部真值文档自查铁律

每次 Read 内部真值文档某段时,必读完整段(不只读 grep 命中行)— 内文可能含真值 cite 但 grep 字面错位漏。

## lint 状态

```bash
# task md / BE 推单 doc 内 grep API 文档但只命中单版本 → 软警告
git diff --name-only | grep -E "task|escalation|btm" | while read -r f; do
    if grep -q "API_SPEC_V1\|agent-detail-api\.md" "$f" && \
       ! grep -q "API_SPEC_V2\|API_SPEC_V3\|agent-detail-api-v2" "$f"; then
        echo "⚠️ $f: 引用 v1 API 文档但未引 v2/v3,检查是否漏读多版本"
    fi
done
```

## 关联

- 协调端 baseline 缺 master。
- 凭印象不查实证(高频复发)。
- 真值源优先级铁律升级为"全版本文档 > 单版本"。
- 不凭印象下发 task。
