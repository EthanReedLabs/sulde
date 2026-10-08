---
doc_id: "tech-docs/案例研究/03-跨端一致性工程/状态模块register-setter竞态与占位补偿"
container: case-studies
platform: none
summary: "**技术域**：移动端状态管理 / Kotlin Coroutines / Swift Concurrency / 双…"
---

# 状态模块 Register/Setter 竞态与占位补偿案例研究

> **技术域**：移动端状态管理 / Kotlin Coroutines / Swift Concurrency / 双端一致性
> **难度**：⭐⭐⭐⭐⭐
> **关键词**：register / setter race / Mutex / coroutine / ConcurrentHashMap / putIfAbsent / Swift actor / withCheckedContinuation / StateFlow / TestDispatcher / 占位补偿
> **可迁移场景**：卡片播放状态、列表项可见性、静音状态、选中状态、视频卡片播放控制、跨端状态模块、异步注册 + 多 setter 的状态容器

---

## 场景与系统架构

某移动端状态模块负责管理列表中每张卡片的“可播放状态”。调用方在卡片绑定时先注册卡片，再设置该卡片的可见性、静音状态、选中状态，最后由 UI 观察状态流决定视频是否应该播放、是否静音。

对外 API 可以抽象为：

```kotlin
interface CardStateModule {
    fun observe(cardId: CardId): StateFlow<PlayableState>
    fun register(cardId: CardId, template: TemplateData)
    fun setVisibility(cardId: CardId, visible: Boolean)
    fun setMuted(cardId: CardId, muted: Boolean)
    fun setSelection(cardId: CardId?)
    fun forget(cardId: CardId)
}
```

内部为了避免多线程同时改状态，使用 actor / mutex 串行化：

```
Caller Thread(s)
├── register(cardId, template)
├── setVisibility(cardId, true)
├── setMuted(cardId, true)
└── setSelection(cardId)
        │
        ▼
State Module
├── entries[cardId]：卡片级状态
│   ├── template
│   ├── visible
│   ├── muted
│   └── loadStatus
├── list-level state
│   └── selectedCardId
├── Mutex / actor：串行处理状态变更
└── StateFlow / observer：向 UI 发射 PlayableState
```

调用方通常按下面顺序写：

```kotlin
module.register(cardId, template)
module.setVisibility(cardId, visible = true)
module.setMuted(cardId, muted = false)
```

问题在于：调用方代码顺序并不等于模块内部入锁顺序。只要这些调用跨 coroutine、跨线程或经过 actor continuation，就可能发生 setter 先于 register 真正执行。

---

## 问题现象

用户可见问题表现为：

1. 卡片已经进入可见区域，但视频不播放。
2. 调用方已经设置静音，但卡片音量状态不符合预期。
3. 某些卡片在快速滚动或快速绑定时状态异常，重进页面或重新绑定后恢复。

从调用方日志看，顺序可能完全正确：

```
register(cardA)
setVisibility(cardA, true)
setMuted(cardA, true)
```

但模块内部真实执行顺序可能变成：

```
setVisibility(cardA, true)
setMuted(cardA, true)
register(cardA)
```

如果 setter 早到时 `entries[cardA]` 还不存在，旧实现会直接找不到 entry，然后丢弃这次 setter。等 register 后 entry 创建完成，`visible` / `muted` 已经回到默认值，导致状态流计算错误。

典型断点：

| 调用 | 预期 | 竞态下实际 |
|---|---|---|
| `setVisibility(cardA, true)` | 卡片注册后 visible=true | entry 不存在，值丢失 |
| `setMuted(cardA, true)` | 卡片注册后 muted=true | entry 不存在，值丢失 |
| `register(cardA)` | 创建 entry 并保留早到 setter | 创建默认 entry，早到值已丢 |
| `observe(cardA)` | 发射可播放 / 静音状态 | 发射默认状态，视频不播或静音异常 |

---

## 根因分析

### 根因一：调用方顺序不等于入锁顺序

很多状态模块会把 public API 写成非阻塞入口，内部再 `launch` 或发送消息到 actor：

```kotlin
fun register(cardId: CardId, template: TemplateData) {
    scope.launch {
        mutex.withLock {
            actor.register(cardId, template)
        }
    }
}

fun setVisibility(cardId: CardId, visible: Boolean) {
    scope.launch {
        mutex.withLock {
            actor.setVisibility(cardId, visible)
        }
    }
}
```

调用方按顺序调用 public API，只能保证 launch 的发起顺序，不保证 coroutine 调度、线程执行和 `mutex.withLock` 获取顺序。Kotlin `Mutex` 在多线程场景下不应被当作严格 FIFO 排队器。先调用的 coroutine 可能后入锁，后调用的 setter 可能先执行。

Swift 侧也有同类问题。actor 能串行化 actor 内部状态，但如果调用经过 `withCheckedContinuation`、任务调度或多个异步入口，调用方发起顺序同样不等于最终进入 actor 处理的顺序。

### 根因二：早到 setter 依赖 entry，但 entry 由 register 创建

旧实现通常是：

```kotlin
private val entries = mutableMapOf<CardId, CardEntry>()

suspend fun setVisibility(cardId: CardId, visible: Boolean) = mutex.withLock {
    val entry = entries[cardId] ?: return       // ❌ 早到 setter 直接丢
    entries[cardId] = entry.copy(visible = visible)
    recompute(cardId)
}

suspend fun register(cardId: CardId, template: TemplateData) = mutex.withLock {
    entries[cardId] = CardEntry(
        template = template,
        visible = false,
        muted = false,
        status = LoadStatus.NotStarted
    )
    startLoad(cardId)
}
```

这段代码隐含了一个前提：`register` 一定先于所有 card-level setter 执行。这个前提在并发调度下不成立。

问题不是 mutex 没用，而是 mutex 只保证“同一时刻一个修改”，不保证“业务所期待的顺序一定发生”。如果早到 setter 在锁内找不到 entry，它仍然会被串行地、稳定地丢掉。

### 根因三：setSelection 属于 list-level state，不受同一 entry 竞态影响

`setSelection(cardId)` 这类列表级状态不依赖 `entries[cardId]` 是否已存在：

```kotlin
suspend fun setSelection(cardId: CardId?) = mutex.withLock {
    selectedCardId = cardId
    recomputeAll()
}
```

因此它和 `setVisibility` / `setMuted` 的风险不同。后两者是 card-level setter，需要有 entry 承接输入；前者可以先保存为 list-level state，等卡片注册后 recompute 时自然生效。

这一区分说明：不能笼统地说“所有 setter 都有 race”。真正危险的是“setter 输入属于某个 card entry，但 entry 尚未创建”的路径。

### 根因四：双端并发机制不同，行为漏洞相同

Android 侧的触发条件来自 coroutine + `Mutex` + 多线程调度；iOS 侧来自 Swift actor + continuation 调度。底层机制不同，但漏洞相同：

```
caller 意图：register -> setter
运行时事实：setter 可能先被状态模块处理
旧行为：entry 不存在 -> setter 丢失
用户结果：状态不生效
```

因此，跨端修复目标不是让实现完全一致，而是让行为契约一致：只要调用方发起过 setter，即使它早于 register 被处理，register 完成后该 setter 的值也必须生效。

---

## 解决方案

### Android：同步占位 entry，早到 setter 直接写入占位

Android 侧采用占位补偿：public `register` 在发送异步注册任务前，先同步确保 entry 存在。

```kotlin
class StateActor {
    private val entries = ConcurrentHashMap<CardId, CardEntry>()

    fun ensureEntryExists(cardId: CardId, template: TemplateData) {
        entries.putIfAbsent(
            cardId,
            CardEntry(
                template = template,
                visible = false,
                muted = false,
                status = LoadStatus.NotStarted
            )
        )
    }
}
```

public API：

```kotlin
fun register(cardId: CardId, template: TemplateData) {
    actor.ensureEntryExists(cardId, template)  // ✅ 同步占位，先于异步入锁

    scope.launch {
        actor.register(cardId, template)
    }
}
```

setter 不再因为 entry 不存在而丢值：

```kotlin
suspend fun setMuted(cardId: CardId, muted: Boolean) = mutex.withLock {
    val entry = entries[cardId] ?: return
    entries[cardId] = entry.copy(muted = muted)
    recompute(cardId)
}
```

register 真正入锁时，如果发现已有 `status == NotStarted` 的占位 entry，只更新 template 等注册必要信息，保留早到 setter 写入的 visible / muted：

```kotlin
suspend fun register(cardId: CardId, template: TemplateData) = mutex.withLock {
    val existing = entries[cardId]

    if (existing != null && existing.status == LoadStatus.NotStarted) {
        entries[cardId] = existing.copy(
            template = template              // ✅ 消费占位，仅补注册数据
            // visible / muted / metadata 保留
        )
        startLoad(cardId)
        return
    }

    if (existing != null) {
        handleAlreadyRegistered(cardId, template, existing)
        return
    }

    entries[cardId] = CardEntry(template = template)
    startLoad(cardId)
}
```

这里使用 `ConcurrentHashMap.putIfAbsent` 是因为占位需要在 mutex 外同步完成，确保 public `register` 返回前 entry 已经存在。后续复杂状态变更仍由 mutex 串行化。

### iOS：pendingPerCardInputs 缓冲，register 后 flush

iOS 侧采用等价但不同形态的修法：早到 setter 不直接要求 entry 存在，而是先进入按 cardId 分组的 pending 缓冲；register 完成后 flush。

抽象结构：

```swift
actor CardStateActor {
    private var entries: [CardId: CardEntry] = [:]
    private var pendingPerCardInputs: [CardId: PendingInputs] = [:]

    func setMuted(cardId: CardId, muted: Bool) {
        guard entries[cardId] != nil else {
            pendingPerCardInputs[cardId, default: .init()].muted = muted
            return
        }
        entries[cardId]?.muted = muted
        recompute(cardId)
    }

    func register(cardId: CardId, template: TemplateData) {
        entries[cardId] = CardEntry(template: template)

        if let pending = pendingPerCardInputs.removeValue(forKey: cardId) {
            apply(pending, to: cardId)        // ✅ register 后补偿早到 setter
        }

        recompute(cardId)
    }
}
```

Android 是“先创建占位 entry，让 setter 有地方写”；iOS 是“先缓存 setter 输入，等 entry 创建后再应用”。实现不同，但行为契约一致。

### 公共 API 签名不变

修复不要求调用方改顺序或 await：

```kotlin
module.register(cardId, template)
module.setVisibility(cardId, visible)
module.setMuted(cardId, muted)
```

这点很重要。竞态发生在模块内部调度，要求所有调用方重写时序既不现实，也无法覆盖未来调用点。状态模块应自己保证 API 的业务不变式。

### 为什么这样修，而不是其他方式

**不强制 caller 顺序**：caller 已经按顺序调用，问题是入锁顺序可能倒置。继续要求 caller “更小心”不能解决 coroutine / actor 调度问题。

**不要求 caller await register 完成**：这会污染 API，增加所有调用点复杂度，并把状态模块内部时序泄露给 UI 层。列表快速 bind 场景也不适合每个卡片阻塞等待 register。

**不使用全局大锁包住 public API**：全局同步大锁会降低并发能力，并可能造成主线程阻塞。更小的补偿结构可以只处理早到 setter 的丢值问题。

**不把 setter 失败静默忽略**：静默忽略是根因。状态模块的契约应是“setter 表达了业务输入”，模块必须让这个输入在 register 后生效，除非 card 已被 forget。

### 测试：用顺序倒置覆盖 race 不变式

真实多线程 race 不稳定，单测不应依赖概率。更可靠的测试方式是故意倒置调用顺序，模拟 setter 先入锁：

```kotlin
@Test
fun visibilityBeforeRegister_isPreserved() = runTest {
    module.setVisibility(cardId, true)
    module.register(cardId, template)

    val state = module.snapshot(cardId)
    assertThat(state.visible).isTrue()
}
```

已验证结果：

| 测试范围 | 数量 | 结果 |
|---|---:|---|
| 新增 race fixture | 5 | 0 failures |
| 全模块单测 | 110 | 0 failures |

新增 5 个 race fixture 覆盖：

1. `setVisibility` 早于 `register` 不丢。
2. `setMuted` 早于 `register` 不丢。
3. `setVisibility` 与 `setMuted` 都早于 `register` 时都生效。
4. `setSelection` 早于 `register` 时作为 list-level state 生效。
5. `forget` 后占位 entry 和元数据被清空。

---

## 可迁移原则

### 1. Caller 顺序不等于锁内顺序

只要 public API 内部使用 coroutine、actor、队列或 mutex，调用方顺序就不应被当作状态处理顺序。模块必须按“任意合法交错”设计。

### 2. 早到输入不能静默丢弃

如果 setter 表达的是业务输入，而目标 entry 可能尚未创建，就需要占位、pending buffer 或重放机制。找不到 entry 就 return，通常只是把 race 变成偶发用户 bug。

### 3. 双端对称看行为契约，不看实现形态

Android 可以用 `ConcurrentHashMap.putIfAbsent` 占位，iOS 可以用 `pendingPerCardInputs` 缓冲。只要保证“setter 早到 register 后仍生效”，就是对称修复。

### 4. 用顺序倒置测试 race 不变式

概率性 race stress test 难稳定。把调用顺序主动倒置，可以确定性覆盖“最坏入锁顺序”，验证模块不变式。

### 5. Register 消费占位时必须保留 setter 字段

占位 entry 不是临时垃圾。register 后如果直接覆盖整个 entry，会再次丢掉 visible/muted。正确做法是只补充 template / load 信息，保留早到 setter 写入的字段。

### 6. forget 必须清理占位和 pending

补偿机制引入了额外状态。卡片离开或被销毁时，必须同时清 entries、flows、pending inputs，避免旧输入污染下一次同 id 注册。

---

## 技术深问 Q&A

### Q1：Kotlin `Mutex` 不是已经串行了吗，为什么还会 race？

`Mutex` 串行的是临界区执行，不保证业务期望的调用顺序一定成为入锁顺序。多个 coroutine 在不同线程调度时，后发起的 setter 可能先拿到锁。

### Q2：为什么不用 `mutableMapOf` 加 mutex 就够了？

占位 entry 需要在 public `register` 中同步创建，发生在 mutex 外，用于保证早到 setter 有 entry 可写。`ConcurrentHashMap.putIfAbsent` 适合这个同步占位场景；复杂状态变更仍由 mutex 管。

### Q3：占位 entry 会不会触发错误播放？

占位 entry 的 `status` 是 `NotStarted`，默认 visible/muted 为安全值。它只是承接 setter 输入，不应直接表示 ready/playable。真正加载和状态计算仍在 register 后执行。

### Q4：iOS 为什么不用同样的占位 entry？

可以，但不必。Swift actor 内用 pending buffer 更自然：setter 早到时记录输入，register 创建 entry 后 flush。实现不同，行为不变式相同。

### Q5：为什么 `setSelection` 早到不需要占位？

因为 selection 是 list-level state，不依赖某个 card entry 是否存在。它可以先保存为全局选中 id，等卡片注册后 recompute 时自然参与计算。

### Q6：如何避免补偿状态泄漏？

所有生命周期结束路径都要清理：`forget(cardId)` 应删除 entry、observer flow、alive flag、pending inputs 或占位元数据。否则同 id 再次注册时可能继承旧状态。
