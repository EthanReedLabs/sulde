# crash-fix Android 参考(`mobile-android`)

> 配套 `../SKILL.md`。Android 特定日志命令 + 崩溃模式 + 验证。

## §1 拉日志命令

### runtime — adb logcat

```bash
# 拉最近 Fatal Exception(zsh 需要单引号包通配符)
adb logcat -d -s AndroidRuntime:E '*:S' | tail -80

# 上面没内容时,只按 tag 过滤
adb logcat -d -s AndroidRuntime:E | tail -80

# 拉 App 进程日志(App 还在运行)
adb logcat -d --pid=$(adb shell pidof <your-app-package> 2>/dev/null) 2>/dev/null | tail -100

# App 已崩溃退出(pidof 无结果),按包名过滤
adb logcat -d | grep -A 30 "<your-app-package>.*FATAL\|<your-app-package>.*Exception" | tail -80
```

**zsh 注意**:`*` 会被 shell 展开,`*:S` 必须单引号包裹。

### build — Gradle 编译错误

```bash
./gradlew assembleDebug 2>&1 | grep -A 5 "error:\|FAILURE\|BUILD FAILED" | head -60

# 特定模块
./gradlew :feature-home:compileDebugKotlin 2>&1 | grep -A 5 "error:" | head -40
```

### anr — Application Not Responding

```bash
adb shell cat /data/anr/traces.txt 2>/dev/null | head -100
# 或
adb bugreport /tmp/bugreport.zip 2>/dev/null
```

### 设备信息

```bash
adb shell getprop ro.product.model
adb shell getprop ro.build.version.release
adb shell getprop ro.build.version.sdk
adb shell dumpsys package <your-app-package> | grep versionName
```

## §2 常见崩溃模式(Android)

| 异常 | 常见原因 | 检查点 |
|---|---|---|
| `NullPointerException` | 强解包 / 假设非 null | `value!!` / `value!!.field` / `state.xxx!!` |
| `IllegalStateException` | state machine 状态非法 | reducer when 分支 / lifecycle / coroutine 在错误 scope |
| `ClassCastException` | unsafe cast | `intent as XxxUserIntent` / `obj as? T` 错用 `as` |
| `IndexOutOfBoundsException` | 列表越界 | RecyclerView adapter / `list[index]` / `subList` |
| `ConcurrentModificationException` | 集合迭代时被改 | for-loop 内 `list.remove(item)` |
| `NetworkOnMainThreadException` | 主线程跑网络 | OkHttp 同步调用 / Room 主线程 query |
| `UnsupportedOperationException` | 不可变集合被改 | `listOf` / `mapOf` 当 mutable 用 |
| `RuntimeException: Could not get resource` | 资源 ID 错 / 不存在 | drawable / id reference 未编译 / 多 module ID 冲突 |
| OOM / `OutOfMemoryError` | 内存泄漏 / 大图未压缩 | LeakCanary / 占位图 size / Bitmap recycle |
| `ANR in com.your.pkg` | 主线程 > 5s | 数据库 / 文件 IO / sleep 在主线程 |

## §3 架构链路诊断(Android MVI)

崩溃在 Store / Reducer 中时:

- 检查 `reduceUser` / `reduceResult` 的 `when` 分支是否覆盖完整(`else -> ` 是否合理)
- 检查 unsafe cast(`intent as XxxUserIntent`)— 应改为 `as?` + null 处理
- 检查 Command 回调是否处理了所有 Result 情况(尤其 error / loading state)
- 检查 coroutine scope 是否正确(`viewModelScope` vs `lifecycleScope` vs `GlobalScope`)
- 检查 Flow `collect` 是否在 lifecycle-aware coroutine 内

崩溃在 Activity / Fragment 中:
- `onCreate` 内 access `findViewById` 前是否 `setContentView`
- `Fragment.requireActivity()` 在 detached state
- `View.context as Activity` 在 ApplicationContext 上调用

## §4 责任 Dev 路径前缀(示例,项目可自定义)

> ⚠️ **占位示例 — 替换为你的项目**
> 下方 table 是某移动创作 app 的 Dev / 模块 mapping,**仅作格式示例**。你的项目应:
> 1. **优先方式**:在 `<docs-hub>/page-owner-map.yaml` 显式定义本项目的 module → Dev mapping,coordinator-maintenance / writing-task-md 等 skill 优先读 yaml
> 2. **备选方式**:直接用你的 `.sulde-config.yaml: team[]` alias 配合实际 module 名替换下表的 `A/B/C` + `feature-home/...`

| 文件路径前缀 | 责任 Dev | 分支前缀 |
|---|---|---|
| `feature-home/` | A | `dev/dev-a/` |
| `feature-discover/` | A | `dev/dev-a/` |
| `feature-detail/` | A | `dev/dev-a/` |
| `feature-create/<sample-agent>/` | B | `dev/dev-c/` |
| `feature-create/<sample-realtime>/` | B | `dev/dev-c/` |
| `core-ui/` | B | `dev/dev-c/` |
| `feature-inbox/` | C | `dev/dev-e/` |
| `feature-profile/` | C | `dev/dev-e/` |
| `feature-auth/` | C | `dev/dev-e/` |
| `core-network/` | C | `dev/dev-e/` |
| `core-storage/` | C | `dev/dev-e/` |
| `core-mvi/` | A | `dev/dev-a/` |
| `app/core/` | A | `dev/dev-a/` |

项目本地实际 mapping 应在 `<docs-hub>/page-owner-map.yaml` 或 `.sulde-config.yaml`。

## §5 验证(repair verify)

```bash
# 1. 编译
./gradlew :{module}:compileDebugKotlin

# 2. 完整 install
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk

# 3. Launch + 触达原崩溃场景
adb shell am start -n {package}/.MainActivity
# (手动操作或脚本驱动到原崩溃路径)

# 4. 抓 30s log,无新 crash
adb logcat -c
sleep 30  # 期间用户操作或脚本驱动
adb logcat -d -s AndroidRuntime:E '*:S' | tail -20
```

验证全过 → handoff `§ verify` 段含上述 4 步证据。

## §6 Android 特定修复模式

- **NPE 防御**:`state.currentItem!!.videoUrl` → `state.currentItem?.videoUrl ?: return`
- **Cast 防御**:`intent as XxxUserIntent` → `(intent as? XxxUserIntent) ?: return`
- **列表防御**:`list[index]` → `list.getOrNull(index) ?: return`
- **主线程违规修**:`runBlocking { repo.fetch() }` → `viewModelScope.launch { ... }`
- **资源 ID 错**:确保 `R.id.foo` 在编译后的同 module 中,跨 module 用 `R.id.foo_in_module` 限定

## §7 ANR 修复(主线程 > 5s)

```bash
# 找 ANR trace
adb shell cat /data/anr/traces.txt | head -200

# 定位 main thread block 在哪
grep -A 20 'main".*tid=' /data/anr/traces.txt
```

修复方向:
- 数据库 query → 改 suspend / Flow,IO dispatcher
- 文件 IO → `Dispatchers.IO`
- 大列表 diff → DiffUtil(在 background)
- 图片解码 → Coil / Glide(自动 background)
- JNI 调用 → 检查 native 实现是否阻塞
