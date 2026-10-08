---
doc_id: "ap-0119"
container: anti-patterns
platform: cross
summary: "通用 UploadService 对纯文件(image / 头像)无分支,落 else 当业务存"
---

# 0119 — 通用 UploadService 对纯文件(image / 头像)无分支,落 else 当业务存

- **平台**:Android / iOS
- **复发次数**:0

## ❌ 错误

通用 `UploadService.upload(type, ...)` 抽象只识别 video / audio 两类业务上传(建档 + 轮询 + 保存),image / 头像 / 纯文件类无独立分支 → **落 else 当主业务处理**:走业务保存路径(建档,语义错位)+ 把**超长签名 URL**(几千字符的预签名 PUT 地址)传作入库 URL → 后端拒 `The URL exceeds the maximum length`。

```kotlin
fun upload(type: UploadType, file: File, ...): UploadResult {
    val signItem = getSignedUrl(file)
    // signItem.signURL          = 超长预签名 PUT 地址,只能用一次 PUT
    // signItem.finalStaticUrl   = 干净 CDN 入库地址
    putToOss(signItem.signURL, file)

    return when (type) {
        UploadType.VIDEO -> saveVideoV3(...)
        UploadType.AUDIO -> saveAudioV3(...)
        else -> saveMusicV3(copyUrl = signItem.signURL)   // ❌ image / 头像落这里
        //       ↑ 当主业务存,且把超长签名 URL 当 copyUrl 入库 → 后端拒
    }
}
data class SignItem(val signURL: String)  // ❌ 缺 finalStaticUrl 字段
```

## 为什么错

- 通用 `UploadService` 抽象初版只考虑业务上传(创作产物),都需建档 + 轮询 + 保存。
- image / 头像 / 纯文件不需建档(OSS 上传后**直接拿干净 CDN 地址**就用),走业务保存路径完全是语义错位。
- `getSignedUrl()` 已返了 `{signURL, finalStaticUrl}` 两个字段,**但 data class 只读了一个**(`signURL`),`finalStaticUrl` 在 adapter 层就丢了。
- `signURL` 设计上**只能 PUT 一次**(预签名 + query 参数,几千字符;入库 / 展示不可能用),`finalStaticUrl` 才是入库 / 展示用的干净地址。
- "落 else 走主业务路径"是 silent — 编译 ok / 上传 OSS ok / **只在后端 schema 校验时报错**,链路前 90% 看不出。

## ✅ 正确

```kotlin
data class SignItem(
    val signURL: String,
    val finalStaticUrl: String   // ✅ 保留入库用的干净 CDN 地址
)

fun upload(type: UploadType, file: File, ...): UploadResult {
    val signItem = getSignedUrl(file)
    putToOss(signItem.signURL, file)

    return when (type) {
        UploadType.VIDEO -> saveVideoV3(...)
        UploadType.AUDIO -> saveAudioV3(...)
        UploadType.IMAGE -> UploadResult.Success(url = signItem.finalStaticUrl)
        //                 ✅ 纯文件分支:不建档不轮询,直接返 finalStaticUrl
        else -> throw IllegalArgumentException("unsupported upload type: $type")
        //      ✅ 拒绝 silent fallback,未支持类型显式抛
    }
}
```

caller 显式区分:PUT 用 `signURL`(一次性预签名),入库 / 展示 / 后端 API 用 `finalStaticUrl`(干净 CDN 地址)。

iOS 同款修法:用 mimeType prefix(`request.mimeType.hasPrefix("image/")`)早返分支,image 直接 yield `finalStaticUrl` + finish,不调业务保存;`SignedUrl` struct 保留 `finalStaticUrl` 字段。

## 判定线(违一即反模式)

1. 通用 `UploadService.upload()` 的 `when (type)` / `switch (type)` 出现 **`else -> 走业务分支`**(非 `throw`)→ ❌ silent fallback。
2. `getSignedUrl()` 返回多字段但 data class 只读 `signURL` 丢 `finalStaticUrl` → ❌。
3. 业务侧把 `signURL`(预签名 PUT 地址)当入库 / 展示 URL 用 → ❌(签名超时失效 + 长度超限)。
4. 纯文件类型上传链路涉及建档 / 轮询 → ❌ 语义错位。

## lint 状态

```bash
# UploadService when(type) 出现 else -> save... 业务分支 → warn
grep -rn 'when.*UploadType\|when.*type:' --include='*.kt' app/src | xargs -I{} bash -c '
    f=$(echo "{}" | cut -d: -f1)
    if grep -q "else ->" "$f" && grep -q "saveMusicV3\|saveVideoV3\|saveAudioV3" "$f"; then
        echo "WARN §0119: $f — UploadService else 分支落业务保存,新类型 silent fallback 高危"
    fi'
# SignItem 字段完整性:缺 finalStaticUrl → warn
```

## How to apply

- 设计通用上传 service 抽象时,纯文件类型(image / pdf / 头像)必有独立分支,**禁 silent else fallback** 落业务保存路径。
- `getSignedUrl` 返回的所有字段 data class 全部保留,不在 adapter 层丢字段。
- 协调端 task md 涉及上传类功能必含 "上传类型分支审计" Step:grep `UploadService.upload` 看 when 分支是否含目标类型。
- `/code-review` checklist 加:upload service when(type) 含 else 业务分支 + 缺 finalStaticUrl 字段。

## 端属性

- Android 首次踩。
- iOS ✅ 已修(对齐 Android):mimeType prefix 判定 image 早返分支,`SignedUrl` struct 已含 `finalStaticUrl`。**双端已覆盖。**

## 关联

- Spec Feature 层抽象 Client 留 Mock 不易察觉(同源:抽象设计漏类型,silent 落错分支)。
- §0117 + §0118 + §0109(同 batch 多层连环修)。
- 协调端 task md baseline 凭印象 master。
