---
doc_id: "ap-0132"
container: anti-patterns
platform: cross
summary: "0132 poll-first 把\"查询失败 null\"当\"无任务\" → 重复付费"
---

# 0132 poll-first 把"查询失败 null"当"无任务" → 重复付费

- **平台**:iOS / Android
- **复发次数**:0

## ❌ 错误

合成链路用 poll-first 模式(发起 create 前先查"是否已有任务"防重复创建)。Bug:查询返 `null` / `throws` 时不区分"查询失败"(网络抖动 / 5xx)vs "真无任务",两种都走 create 分支 → 重复合成 → 重复付费:

```kotlin
val first = getTaskDetail(referenceId).getOrNull()
when {
    first?.status == SUCCESS -> applyFinalVideo(...); return
    first?.status == RENDERING -> /* 轮询 */
    else -> {
        // ⚠️ null 可能是 ① 真无任务 → 应 create ② 查询失败 → 不应 create
        // ↓ 不区分,都 create → 若 ① 已存在则重复扣费
        createTask(referenceId, buildMergeConfig())
    }
}
```

后果:网络抖动场景重启/返回触发再跑 → 查询失败返 null → 误判"无任务" → create → 后端再扣费建第二个任务。**涉钱反模式,高严重度**,常跨多 Feature 同 commit 引入。

## 为什么错

只有当查询**成功返回且明确为 null(真无任务)**时才该 create;失败时 create = 用同一不确定信号触发付费副作用。

## ✅ 正确

失败重试 + 区分 success(null=真无)vs failure(throws),failure 路径不 create:

```kotlin
var first: TaskDetail? = null; var firstError: Throwable? = null
repeat(3) { attempt ->
    try { first = getTaskDetail(referenceId); firstError = null; return@repeat }
    catch (e: Throwable) { firstError = e; if (attempt < 2) delay(2000) }
}
if (firstError != null) { emit Failed("查询状态失败,请重试"); return }  // ⚠️ 关键:不 create
when {
    first?.status == SUCCESS -> applyFinalVideo(...)
    first?.status == RENDERING -> /* 接管既有轮询,不 create */
    else -> createTask(referenceId, buildMergeConfig())  // null = 真无任务 → 安全 create
}
```

**第二口子(同 family)**:任务进行中(RENDERING)时也须**接管既有轮询**而非 create — 否则 resume 时已有进行中任务仍 create → 第二次扣费。

铁律:
1. poll-first 涉付费副作用(create / submit / pay / 扣费)必含失败重试(N≥3)+ 区分 success/failure + failure 不触发付费。
2. RENDERING 命中 → 接管轮询,不 create。
3. 跨端共享 poll-first 必同时审查(同语义 bug 常同 commit 引入)。
4. 单测覆盖 failure 路径 + RENDERING 路径(verify 不调 create)。

## lint 状态

❓ 中等(语义检查)— soft 警告:函数含 poll-first 注释 / `getOrNull` 后接 create 调用且无 retry pattern → 警告"可能重复付费"。

## 关联

- 非幂等 effect 无防重入(同源:重复触发付费;该反模式是 UI 层防重入,本反模式是 poll-first 失败路径防重入)
- boolean 语义不明 + 跨端共享逻辑同 commit 同款 bug 一铺多端
