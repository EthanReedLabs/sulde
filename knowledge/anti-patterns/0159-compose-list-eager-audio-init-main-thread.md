---
doc_id: "ap-0159"
container: anti-patterns
platform: android
summary: "Compose 懒列表 item 在组合期同步初始化音频元数据与播放器"
---

# 0159 — Compose 懒列表 item 在组合期同步初始化音频元数据与播放器

- **平台**:Android
- **复发次数**:1
- **lint 状态**:⏳ pending(可扫描 `@Composable` / `remember` 中的 `MediaMetadataRetriever`、`MediaPlayer.prepare()`)

## ❌ 错误

聊天、评论或动态列表中的语音 item 在进入 Composition 时立即:

1. 创建 `MediaMetadataRetriever` 并读取时长;
2. 创建 `MediaPlayer`;
3. 设置音频数据源;
4. 调用同步 `prepare()`。

开发者把这些操作放进 `remember(uri) { ... }`,误以为 `remember` 会把工作移到后台。分页、稳定 key、图片缩略图缓存完成后,列表滑动仍持续掉帧。

## 为什么错

`remember` 只保存计算结果,不会改变计算线程。首次组合仍在 Compose UI 线程执行 block。LazyColumn 滑动时,每个新进入可视区域的语音 item 都会触发一次同步媒体初始化。

真机帧统计呈现典型特征:

- janky frame 比例约 11%;
- UI thread slow frame 数量与 missed deadline 基本一致;
- GPU P90 仅约 4ms,慢 bitmap upload 近乎没有;
- 滑动时日志连续出现主线程 metadata / player 初始化。

这组证据排除了 GPU 绘制和图片上传作为主因。仅增加分页或媒体图片缓存不会修复音频 item 的主线程阻塞。

同步 `MediaPlayer.prepare()` 还会触碰文件描述符、extractor、codec 和音频管线。单次成本可能不高,但快速滑动会把多次初始化压进连续帧预算。

## ✅ 正确

列表 item 的组合路径保持纯 UI:

```kotlin
@Composable
fun AudioRow(model: AudioUiModel) {
    // 时长由持久化模型 / 上传结果提供,不在这里读媒体 metadata
    Text(model.durationLabel)

    PlayButton(
        onClick = {
            controller.play(model.uri) // 点击后才创建 / 复用播放器
        },
    )
}
```

播放器策略:

```kotlin
fun play(uri: Uri) {
    MediaPlayer().apply {
        setDataSource(context, uri)
        setOnPreparedListener { it.start() }
        setOnErrorListener { player, _, _ ->
            player.release()
            true
        }
        prepareAsync()
    }
}
```

工程规则:

1. 时长在录制完成、上传入库或后台预处理阶段计算并持久化;列表只消费展示模型。
2. 未点击的语音 item 不创建播放器。
3. 首次点击后使用 `prepareAsync()`,禁止列表 item 调用同步 `prepare()`。
4. 多条语音需要快速切换时,由页面级或应用级 controller 管理单播放器复用、互斥播放和释放,不要让每个 item 永久持有播放器。
5. item 离屏时只释放 UI 状态;媒体资源生命周期由 controller 明确管理,避免滚动回收触发播放器风暴。
6. 修复前后使用相同真机路径与 `gfxinfo framestats` / Perfetto 对比 UI、GPU、输入延迟和 P95/P99。

## lint 状态

- ⏳ 可实现静态扫描:`@Composable` 函数或 `remember` block 中出现 `MediaMetadataRetriever`、`MediaPlayer()`、`.prepare()` 时报警。
- `.prepareAsync()` 只在显式点击路径或播放器 controller 中允许。
- Code review checklist:媒体列表必须回答“未点击 item 是否创建播放器”和“metadata 在哪一层产生”。
