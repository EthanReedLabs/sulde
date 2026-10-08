---
doc_id: "ap-0139"
container: anti-patterns
platform: cross
summary: "0139 duration 秒→ms 先截断后乘(单位口径漂移)"
---

# 0139 duration 秒→ms 先截断后乘(单位口径漂移)

- **平台**:Android / iOS(跨端架构对照)
- **复发次数**:1

## ❌ 错误

```kotlin
// ❌ 先 toLong 截断再 ×1000
durationMs = (info.duration?.toLong() ?: 0L) * 1000L
// 281.5s → toLong 先截成 281 → ×1000 = 281000ms(丢 0.5s,最坏丢近 1s)
```

同一换算 inline 复制两处:一处截断、一处 `(duration * 1000).toLong()` 保留小数 → **同对象两路时长不一致**。

## 为什么错

- 后端 `duration` 是 Float 秒,`toLong()` 先把秒截成整秒,小数永久丢失。
- 单位换算 inline 复制到多个调用点 → 口径漂移。

## ✅ 正确

抽单一 helper,两路统一调,先 ×1000 保留小数再 toLong:

```kotlin
internal fun durationSecToMs(durationSec: Float?): Long =
    ((durationSec ?: 0f) * 1000f).toLong()   // 先 ×1000 再 toLong
```

精度:歌曲时长(数十~数百秒)乘积 ≤ float32 精确整数区 2^24,无 off-by-1;亚秒场景需 `roundToLong`。

双端架构差异:

| 端 | 实施 | 陷阱状态 |
|---|---|---|
| store 层直接转 ms 存 `durationMs: Long` | adapter format | ❌ 复发(选中态截断 + 漂移)|
| store 层**保留 sec Float 不转 ms**,view format 层转 | view format | ✅ 架构天然规避(不在 store 层做有损转换)|

→ 延迟单位转换到 view format 层,避免 store 层精度有损 + 防多 caller 漂移。

**根本教训**:单位换算(sec→ms / dp→px / 货币)禁止 inline 复制到多个调用点 → 抽单一 helper 防漂移;若可延迟则在 view format 层做。

## lint 状态

✅ 已实施(Android)— 检测 `duration.*\.toLong\(\).*\*\s*1000` 截断后乘形态;正确形态 `(x*1000f).toLong()` 不误报。iOS 待补(`Int(...duration...)` 截断 + `* 1000` 形态)。

## 关联

- RGBA↔ARGB 跨端陷阱(同源:单位/格式跨端口径)
