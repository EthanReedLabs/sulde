---
doc_id: "ap-0118"
container: anti-patterns
platform: android
summary: "Coil 默认 allowHardware=true → HARDWARE bitmap 画到软件 Canvas 全黑"
---

# 0118 — Coil 默认 allowHardware=true → HARDWARE bitmap 画到软件 Canvas 全黑

- **平台**:Android(iOS 架构差异不命中)
- **复发次数**:0

> **特点**:静默 bug,**非崩溃** — 上传链路全跑通、网络 200、回页 load 成功,但裁剪输出 / 缩略图 / 预览全黑。极易当 OSS 上传问题 / 服务端 resize 问题误诊。

## ❌ 错误

Android Coil ImageLoader **默认 `allowHardware=true`**(性能优化,节省 GPU 上传)→ Coil 解码出的 bitmap 是 `Bitmap.Config.HARDWARE`(GPU-side texture,CPU 不可读)。代码若用 `View.drawToBitmap()` / 手动 `Canvas(softwareBitmap)` 画 HARDWARE bitmap → **画不上去,Canvas 留全黑** — 不抛异常、不打 log,完全静默。

```kotlin
val previewImageView: ImageView = findViewById(R.id.imgAvatarPreview)
previewImageView.load(sourceUri)  // Coil 默认 allowHardware=true → HARDWARE bitmap 上屏

val cropped: Bitmap = previewImageView.drawToBitmap()  // ❌ 软件 Canvas 画 HARDWARE bitmap → 全黑
uploadToOss(cropped)  // 网络 200 / OSS PUT ✅ — 但 byte 是全黑 JPEG
```

**现象链**:选图 → 裁剪页 IV 显示**正常**(GPU 直接画到屏幕)→ 点 Upload → `drawToBitmap()` 软件 Canvas 渲染 IV → HARDWARE bitmap 不可读 → 留全黑 → 上传 / 后端 / 回页 load 全链路没毛病,头像就是全黑 → logcat **0 异常**。

## 为什么错

- `allowHardware=true` 默认 → 节省 GPU upload,显著省内存。
- `Bitmap.Config.HARDWARE`(API 26+):**像素存 GPU memory,CPU 不可直接读** — `getPixel`/`Canvas.drawBitmap` 全失败。
- **失败方式是静默**:`Canvas.drawBitmap(hwBitmap, ...)` 不抛 exception,只在内部"画失败"(SkCanvas 看到 HARDWARE 直接 skip)。
- 上屏走 GPU 路径正常,看不出问题。
- 任何"取 ImageView 内容当像素源"路径(`drawToBitmap` / 手动 Canvas / 截屏 / 模糊滤镜 / 水印 / 裁剪)都失败,**只是默默全黑**。
- 同款 bug 在 `allowHardware=false` 下不复现 → 极易漏。

## ✅ 正确

```kotlin
// 方案 A(推荐):跳过 Coil,自己 BitmapFactory 软件解码原图
val opts = BitmapFactory.Options().apply {
    inPreferredConfig = Bitmap.Config.ARGB_8888   // 显式软件配置
    inMutable = true
}
val sourceBitmap = contentResolver.openInputStream(sourceUri)!!.use {
    BitmapFactory.decodeStream(it, null, opts)!!
}
val cropped = Bitmap.createBitmap(sourceBitmap, x, y, w, h)  // ✅ 真正裁剪
uploadToOss(cropped)

// 方案 B(用 Coil 但局部禁 hardware):
imageView.load(sourceUri) {
    allowHardware(false)
    target { drawable -> cropAndUpload(drawable.toBitmap()) }
}

// 方案 C(API 26+ — PixelCopy 从 SurfaceView/GPU 读回 software bitmap,SurfaceView 专用):
PixelCopy.request(surfaceView, softwareBitmap, { result -> ... }, handler)
```

## 判定线(违一即反模式)

1. **任何 `View.drawToBitmap()` / 手动 `Canvas(softwareBitmap)` 取 ImageView 内容当像素源** + ImageView 通过 Coil `load()` 喂图 + ImageLoader 未显式 `allowHardware(false)` → ❌。
2. 等价错法:`bitmap.getPixel()` / `bitmap.copy(ARGB_8888, true)` 拿 HARDWARE bitmap 都失败(拿到全黑)。
3. 正例特征:① BitmapFactory + `inPreferredConfig=ARGB_8888`;② Coil `load { allowHardware(false) }`;③ PixelCopy。
4. **静默 bug 判定**:上传 byte 全黑 / 缩略图全黑 / 滤镜出全黑 + logcat 0 exception → 必查 Coil `allowHardware` 默认 true 路径。

## lint 状态

```bash
# 启发式:同文件含 Coil `.load(` + `drawToBitmap()` / `Canvas(` 且未禁 allowHardware → 软警告
grep -rn -l '\.load(' --include='*.kt' . | while read f; do
    if grep -q 'drawToBitmap\|Canvas(' "$f" && ! grep -q 'allowHardware(false)\|inPreferredConfig.*ARGB_8888' "$f"; then
        echo "WARN §0118: $f — Coil load + drawToBitmap/Canvas 未禁 allowHardware,HARDWARE bitmap 软件 Canvas 全黑高危"
    fi
done
```

运行期 bitmap config 类型静态扫不出,启发式只能粗筛。最终靠 `/code-review` 人工 + 真机实证(上传 byte 真黑 → 必查 allowHardware)。

## How to apply

- 涉及"取 ImageView 内容做像素操作"路径(裁剪 / 截屏 / 水印 / 滤镜 / 上传 byte)必显式禁 hardware bitmap。
- 协调端 task md 涉及裁剪 / 截屏 / 水印类 UI 时,代码示例必含软件解码路径,**禁直接 `imageView.drawToBitmap()`**。
- 真机验证铁律:上传 / 截屏 / 像素操作类功能必跑真机验证 byte 真值(不能只看屏幕显示 — 屏幕走 GPU 路径,看不出全黑)。

## 端属性

- Android 首次踩。
- iOS:**架构差异不命中** — SwiftUI declarative render 无 `drawToBitmap` / 软件 Canvas 调用;`UIScrollView` wrap `UIImageView` zoom + pan 是 GPU render 路径;`UIImage` 无 HARDWARE config 等价(`CGImage` 直接可读)。**Android-only。**

## 关联

- §0117(Coil crossfade → CrossfadeDrawable 强转 — 上游姐妹反模式,同 commit 一并修)。
- §0109(URI 跨 Activity 权限 — 同 batch 链路最上游)。
- 协调端 task md baseline 凭印象 master。
