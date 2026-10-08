---
doc_id: "ap-0117"
container: anti-patterns
platform: android
summary: "Coil 全局 crossfade → ImageView.drawable 强转 BitmapDrawable 崩"
---

# 0117 — Coil 全局 crossfade → ImageView.drawable 强转 BitmapDrawable 崩

- **平台**:Android(iOS 架构差异不命中)
- **复发次数**:0

## ❌ 错误

App 装全局 `ImageLoader { .crossfade(200) }`(Coil 推荐 UX 加 fade 过渡),之后任何 `imageView.load(url)` 完成后 `imageView.drawable` 不是 `BitmapDrawable` 而是 **`coil.drawable.CrossfadeDrawable`**(Coil 内部 wrap 双 frame 用于淡入淡出动画)。代码若假设 `imageView.drawable as BitmapDrawable` 取 bitmap → `ClassCastException` 崩。

```kotlin
val bitmap = (avatarImageView.drawable as BitmapDrawable).bitmap  // ❌ ClassCastException
val cropped = Bitmap.createBitmap(bitmap, x, y, w, h)
uploadToOss(cropped)
```

**crash 链**:`java.lang.ClassCastException: coil.drawable.CrossfadeDrawable cannot be cast to android.graphics.drawable.BitmapDrawable`。

## 为什么错

- 全局 `ImageLoader.Builder(context).crossfade(200).build()` 是项目默认 UX 配置(全 App 适用)。
- Coil `crossfade` 启用后,`Target.onSuccess(drawable)` 收到的是 `CrossfadeDrawable`(包裹旧 frame + 新 frame 做 fade),不是 `BitmapDrawable`。
- `imageView.drawable` getter 返回的就是这个 wrap。
- 任何 `(imageView.drawable as BitmapDrawable).bitmap` 假设全局都崩 — **不是偶发,是必然**(只要全局 crossfade + 业务跑过 `load()`)。
- 同款 bug 在禁用 crossfade(默认)的 Coil 项目里不复现 → review 时极易漏。

## ✅ 正确

```kotlin
// 方案 A(推荐):androidx-core-ktx 的 Drawable.toBitmap() 扩展 — 内置 wrap 类型适配
import androidx.core.graphics.drawable.toBitmap
val bitmap = avatarImageView.drawable?.toBitmap() ?: return
// .toBitmap() 内部:BitmapDrawable 直接拿 .bitmap;CrossfadeDrawable / GifDrawable 等 → 软件 Canvas 渲染

// 方案 B(显式控制软件 Canvas + ARGB_8888 — 像素操作场景,配合 §0118 一并修):
val opts = BitmapFactory.Options().apply { inPreferredConfig = Bitmap.Config.ARGB_8888 }
val source = contentResolver.openInputStream(sourceUri)!!.use { BitmapFactory.decodeStream(it, null, opts)!! }
val cropped = Bitmap.createBitmap(source, x, y, w, h)

// 方案 C(局部禁 crossfade — 治标不治本,仍需自己拿原始 bitmap):
imageView.load(url) { crossfade(false) }
```

像素操作场景用方案 B(裁剪要做软件 Canvas 像素操作,顺带解 §0118 hardware bitmap 全黑),不走 Coil 取 drawable 路径。

## 判定线(违一即反模式)

1. App 装了**全局** `ImageLoader { .crossfade(true / N) }` → 全 App 默认 wrap。
2. 业务代码出现 `as BitmapDrawable` / `instanceof BitmapDrawable` 假设 → ❌。
3. 等价错法:`((BitmapDrawable) drawable).getBitmap()`。
4. 正例特征:用 `Drawable.toBitmap()` / 自己 BitmapFactory 解码原图 / Coil `target` callback 拿原始 bitmap。

## lint 状态

```bash
# 全仓 grep `as BitmapDrawable` / `as? BitmapDrawable` → 软警告
grep -rn 'as BitmapDrawable\|as? BitmapDrawable' --include='*.kt' . | while read line; do
    echo "WARN §0117: $line — Coil + 全局 .crossfade 下 drawable 是 CrossfadeDrawable,强转 BitmapDrawable 必崩"
done
```

## How to apply

- 改"取 ImageView 当前图当像素源"路径,**禁 `as BitmapDrawable`**,用 `Drawable.toBitmap()` 或自解码原图。
- 协调端 task md 涉及 Coil load 后取 bitmap 时,代码示例必含 `Drawable.toBitmap()` 或 BitmapFactory 软件解码。
- 全局 `.crossfade(200)` 不可轻删(全 App UX 依赖);本款是"做像素操作时绕开 Coil drawable 取原图"路径教学,不是"删 crossfade"。

## 端属性

- Android 首次踩。
- iOS:**架构差异不命中** — image loader(Kingfisher / SDWebImage)无 Coil 全局 crossfade 副作用,`UIImage` 在 cache 内是纯 UIImage,无 wrap 强转链路。**但同源 UX 问题(新 CDN URL 首次 load cache miss 闪占位)需对照修**(上传成功 effect 内预存 L1 memory + L2 disk cache,对齐 Android 预热磁盘缓存)。

## 关联

- §0118(Coil HARDWARE bitmap 软件 Canvas 全黑 — 下游姐妹反模式,同 commit 一并修)。
- §0109(URI 跨 Activity 权限 — 同 batch)。
- 协调端 task md baseline 凭印象 master。
