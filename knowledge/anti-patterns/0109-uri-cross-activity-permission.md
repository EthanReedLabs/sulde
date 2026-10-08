---
doc_id: "ap-0109"
container: anti-patterns
platform: android
summary: "URI 跨 Activity FLAG_GRANT_READ_URI_PERMISSION 未传"
---

# 0109 — URI 跨 Activity FLAG_GRANT_READ_URI_PERMISSION 未传

- **平台**:Android
- **复发次数**:2

## ❌ 错误

`startActivity(intent.putExtra("uri", contentUri.toString()))` 把 `content://` URI 当**字符串 extra** 传给跨 Activity,**未 `addFlags(FLAG_GRANT_READ_URI_PERMISSION)` + `setData(uri)`** → 目标 Activity 读不了 URI → image loader(coil / Glide)静默失败(内部吞 SecurityException)→ 预览空白。

```kotlin
val intent = Intent(context, CropActivity::class.java)
intent.putExtra("uri", contentUri.toString())  // ❌ 仅字符串,无权限
startActivity(intent)
// → CropActivity 收到 URI 字符串 → loader.load(uri) 静默失败 → ImageView 空白
```

## 为什么错

Android URI 临时读权限**只授给发起方 Activity**;通过 String extra 传 URI 不带权限;`GetContent` ActivityResult 返回的 URI 也只对调用方有效。

**关键机制**:`Intent.data` 自动带 URI 权限,但 `Intent.putExtra` 内的 Uri **不自动** — 必须 `setClipData(ClipData.newUri(...))` 才让 extras 内 Uri 生效(API 26+ 才支持)。

## ✅ 正确

```kotlin
// 方案 A:setData + FLAG_GRANT_READ_URI_PERMISSION(推荐 — 系统级临时授权)
val intent = Intent(context, CropActivity::class.java).apply {
    setData(contentUri)
    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
}
startActivity(intent)

// 方案 A':extras 内传 Parcelable Uri(非 toString)+ setClipData(API 26+)
val intent = Intent(context, CropActivity::class.java).apply {
    putExtra("uri", contentUri)  // Parcelable Uri
    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    clipData = ClipData.newUri(contentResolver, "uri", contentUri)  // extras 内 Uri 才生效
}
startActivity(intent)
// 收端:getParcelableExtra<Uri>(key, Uri::class.java) + API<33 fallback

// 方案 A'':ACTION_SEND 的 EXTRA_STREAM 同样必须显式授权
val shareIntent = Intent(Intent.ACTION_SEND).apply {
    type = mimeType
    putExtra(Intent.EXTRA_STREAM, contentUri)
    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    clipData = ClipData.newUri(contentResolver, "shared-content", contentUri)
}

// 方案 B:先 copy 到 app cache 再传(URI 跨进程 / 长时间持有时用)
val cachedFile = copyToAppCache(contentUri)
intent.putExtra("local_path", cachedFile.absolutePath)
```

## 判定线

跨 Activity 或通过 `ACTION_SEND` 传 `content://` URI / file picker URI 时,grep `setData\|ClipData\|FLAG_GRANT_READ_URI_PERMISSION` 命中 ≥1。若 0 命中且通过 `putExtra("...", uri.toString())` 或 `EXTRA_STREAM` 传 → 反模式。

## lint 状态

```bash
# 命中 putExtra 传 content:// 字符串且同文件未 grep FLAG_GRANT → warn
grep -rn 'putExtra.*\.toString()' --include='*.kt' feature-*/src | while read line; do
    file=$(echo "$line" | cut -d: -f1)
    if grep -q 'content://' "$file" && ! grep -q 'FLAG_GRANT_READ_URI_PERMISSION' "$file"; then
        echo "WARN §0109: $line — content URI 跨 Activity 传字符串缺权限"
    fi
done
```

## 关联

- 协调端凭技术名词推断真因(本款靠真机抓 URI + Intent extras 实证 coil 静默吞 SecurityException 假说成立)。
- 协调端凭印象不查真值 master。
- 跨端关联:iOS image picker 返回 URL 本就是 file:// 不存在此问题。
- `FileProvider` 生成引用不等于授予读取能力；chooser 选中的第三方应用也必须从发送 Intent 获得临时 grant，多 URI 场景还需完整设置 `ClipData`。
