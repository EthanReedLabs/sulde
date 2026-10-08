---
doc_id: "ap-0110"
container: anti-patterns
platform: android
summary: "裸 toLong / toInt 解析外部 ID 串"
---

# 0110 — 裸 toLong / toInt 解析外部 ID 串

- **平台**:Android(iOS 等价 `Int(string)!` 反模式同源)
- **复发次数**:0

## ❌ 错误

外部传入 id 字符串(`getStringExtra` extras / URL param / SSE field / push payload)用裸 `.toLong()` / `.toInt()` 解析 → 格式不符即抛 `NumberFormatException`,若在 `lifecycleScope.launch` / `viewModelScope.launch` 内未捕获 → app crash。

```kotlin
private fun handleRemixIntent() {
    val remixItemId = intent.getStringExtra("remix_item_id") ?: return
    lifecycleScope.launch {
        val itemId = remixItemId.toLong()  // ❌ "feed_effects_401".toLong() → NFE → crash
        // ... fetch by itemId
    }
}
```

## 为什么错

外部 id 串往往带模块前缀(如 feed item id `feed_xxx_<n>`),跨模块 parse 时若假设"纯数字 id" → 裸 toLong 抛;Kotlin 标准库 `String.toLong()` 在 invalid 时抛 NumberFormatException(不是返 null),需用 `toLongOrNull()` 显式守卫。

## ✅ 正确

```kotlin
private fun handleRemixIntent() {
    val remixItemId = intent.getStringExtra("remix_item_id") ?: return
    lifecycleScope.launch {
        val itemId = remixItemId.substringAfterLast('_').toLongOrNull()
        if (itemId == null) {
            Toast.makeText(this@HostActivity, "Invalid remix id", Toast.LENGTH_SHORT).show()
            finish()
            return@launch
        }
        // ... fetch by itemId
    }
}
```

**关键**:
- `substringAfterLast('_')` 剥前缀(`feed_xxx_401` → `401`,纯数字 id 原样)。
- `toLongOrNull()` 而非 `toLong()` — 返 null 不抛。
- null 时显式 Toast / finish,**非 try/catch 吞栈**(那是反模式 — 修真因 = 解析正确化)。

## 判定线

grep 以下模式命中且无 null 守卫 → 反模式:

```bash
grep -rn 'getStringExtra.*\.toLong()' --include='*.kt' feature-*/src
grep -rn 'getStringExtra.*\.toInt()' --include='*.kt' feature-*/src
grep -rn '\.queryParameter.*\.toLong()' --include='*.kt' feature-*/src
```

## lint 状态

```bash
grep -rn 'getStringExtra\|queryParameter\|getString' --include='*.kt' feature-*/src \
  | grep -E '\.toLong\(\)|\.toInt\(\)' | grep -v 'OrNull' \
  | while read line; do echo "WARN §0110: $line — 外部 id 串裸 toLong/toInt 缺 OrNull 守卫"; done
```

## 关联

- 协调端凭技术名词推断真因(extras 缺字段假说错)。
- 协调端凭印象不查真值 master。
- 跨模块约定:feed id 带前缀,跨模块 parse 必剥前缀。
- iOS 对应反模式:`Int(string)!`(force unwrap)同源,iOS 用 `Int(string)` 返 `Int?` 后 guard。
