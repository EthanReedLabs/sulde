# perf-diagnose Android 参考(`mobile-android`)

> 配套 `../SKILL.md`。Android 特定 profiler 命令 + 指标读法 + 平台模式。

## §1 工具速查表

| 维度 | 首选工具(GUI) | 自动化方案(命令行) |
|---|---|---|
| CPU / 调用栈 | Android Studio CPU Profiler → Flame Chart | `adb shell perfetto` → ui.perfetto.dev |
| 自定义时间线标记 | `android.os.Trace.beginSection` | 代码插桩 + Perfetto |
| 帧率量化 | gfxinfo framestats | `adb shell dumpsys gfxinfo framestats` |
| 帧流水线底层 | SurfaceFlinger --latency | `adb shell dumpsys SurfaceFlinger --latency` |
| 实时帧率可视化 | GPU 渲染条形图(开发者选项) | `adb setprop debug.hwui.show_dirty_regions_overlay` |
| 启动时间 | `am start-activity -W` / logcat Displayed | `adb shell am start-activity -W` |
| 启动链路 | Studio CPU Profiler / Perfetto Startup | `adb shell perfetto`(startup config) |
| JVM 内存分配 | Studio Memory Profiler | `adb shell dumpsys meminfo` |
| Native 内存分配 | Heapprofd | `adb shell perfetto`(heapprofd config) |
| 内存泄漏 | LeakCanary(集成) | `adb logcat -s LeakCanary` |
| 主线程 IO | StrictMode | `adb logcat \| grep StrictMode` |
| 网络瀑布 | Charles / Studio Network Profiler | `adb logcat -s OkHttp` |
| 过度绘制 | 开发者选项可视化 | `adb setprop debug.hwui.overdraw show` |
| 性能回归防护 | Macrobenchmark | `./gradlew :benchmark:connectedAndroidTest` |

---

## §2 按问题类型跑诊断套件

### §2.1 滚动卡顿 / jank

#### A-1. CPU 火焰图(Studio Profiler)

```
1. Android Studio → Run → Profile(工具栏 Profile 按钮)
2. Profiler 面板 → CPU 区域 → Record
3. 模式选 Java/Kotlin Method Trace(精确)或 Callstack Sample(低开销)
4. 真机重现滚动 15s → Stop
5. Flame Chart:主线程最宽块 = jank 根因
6. 截图保存到 .ai-workspace/diag/{date}-{slug}-flame.png
```

#### A-2. Perfetto(systrace 继任,推荐自动化)

```bash
PACKAGE="<your-app-package>"
OUTPUT=".ai-workspace/diag/$(date +%Y-%m-%d)-perfetto.pftrace"
mkdir -p .ai-workspace/diag

adb shell am start -n "$PACKAGE/.MainActivity"
sleep 2

adb shell perfetto \
  --config - --txt \
  --out /data/misc/perfetto-traces/trace.pftrace \
  << 'EOF'
duration_ms: 10000
buffers { size_kb: 131072 }
data_sources {
  config {
    name: "android.surfaceflinger.frametimeline"
  }
}
data_sources {
  config {
    name: "track_event"
  }
}
data_sources {
  config {
    name: "linux.ftrace"
    ftrace_config {
      ftrace_events: "sched/sched_switch"
      ftrace_events: "sched/sched_wakeup_new"
      ftrace_events: "power/cpu_frequency"
    }
  }
}
EOF

sleep 12
adb pull /data/misc/perfetto-traces/trace.pftrace "$OUTPUT"
echo "打开 https://ui.perfetto.dev 拖入 $OUTPUT"
```

**读法**:
- 主线程宽块 > 16ms = 掉帧直接根因
- RenderThread spike = GPU 渲染瓶颈
- "意外出现在主线程" 的 inflate / IO / SharedPreferences = 必须移后台
- Wall Clock > CPU Time = 在等锁或 IO

#### A-3. 帧率量化(gfxinfo,无需 IDE)

```bash
PACKAGE="<your-app-package>"

adb shell dumpsys gfxinfo "$PACKAGE" reset
echo "请在真机滚动列表约 10 秒..."
sleep 10

adb shell dumpsys gfxinfo "$PACKAGE" framestats \
  | tee ".ai-workspace/diag/$(date +%Y-%m-%d)-gfxinfo.txt"

echo "=== 帧率汇总 ==="
adb shell dumpsys gfxinfo "$PACKAGE" \
  | grep -E "Janky frames|Total frames|50th|90th|95th|99th percentile"
```

**示例输出读法**:
```
Total frames rendered: 487
Janky frames: 42 (8.62%)    ← > 5% = 用户明显感知 jank
50th percentile: 6ms
90th percentile: 18ms        ← > 16ms = 有掉帧
95th percentile: 28ms        ← 严重
99th percentile: 72ms        ← 极端卡顿帧
```

### §2.2 自定义时间线标记(代码插桩)

```kotlin
import android.os.Trace

Trace.beginSection("HomeFeed.loadMore")
try {
    viewModel.loadMore()
} finally {
    Trace.endSection()
}

// AndroidX 兼容(API 14+)
import androidx.core.os.TraceCompat
TraceCompat.beginSection("HomeFeed.recyclerBind")
// ...
TraceCompat.endSection()
```

配合 Perfetto 抓取后,自定义 slice 与 RenderThread / Choreographer 时间轴对齐。

### §2.5 启动时间

```bash
PACKAGE="<your-app-package>"

# 同步等待(最快)
adb shell am start-activity -W \
  -n "$PACKAGE/.MainActivity" \
  -a android.intent.action.MAIN
# 输出 ThisTime / TotalTime / WaitTime

# logcat Displayed(更精确,含完整渲染时间)
adb logcat -c
adb shell am start "$PACKAGE"
adb logcat -v time | grep -m 1 "Displayed"

# 冷启动 5 次取均值
for i in 1 2 3 4 5; do
  adb shell am force-stop "$PACKAGE"
  sleep 1
  adb shell am start-activity -W -n "$PACKAGE/.MainActivity" 2>&1 | grep "TotalTime"
done
```

### §2.6 启动链路(Perfetto App Startup 模板)

```bash
adb shell am force-stop <your-app-package>
sleep 1

adb shell perfetto \
  --config - --txt \
  --out /data/misc/perfetto-traces/startup.pftrace \
  << 'EOF'
duration_ms: 8000
buffers { size_kb: 65536 }
data_sources {
  config {
    name: "track_event"
    track_event_config {
      enabled_categories: "startup"
    }
  }
}
data_sources {
  config { name: "android.app_wakelocks" }
}
EOF

adb shell am start <your-app-package>/.MainActivity
sleep 8
adb pull /data/misc/perfetto-traces/startup.pftrace \
  ".ai-workspace/diag/$(date +%Y-%m-%d)-startup.pftrace"
```

### §2.7 内存(JVM Heap)

```bash
PACKAGE="<your-app-package>"

# 当前内存概览
adb shell dumpsys meminfo "$PACKAGE" \
  | tee ".ai-workspace/diag/$(date +%Y-%m-%d)-meminfo.txt"

# 关键指标
adb shell dumpsys meminfo "$PACKAGE" \
  | grep -E "TOTAL|Native Heap|Dalvik Heap|Views:|Activities:"

# 实时监控
PID=$(adb shell pidof "$PACKAGE")
adb shell top -p "$PID" -d 1
```

**Studio Memory Profiler**:Profile → Memory → Record(heap dump / allocation),按 Retained Size 排序找最大对象。Activity / Fragment 实例数 > 1 = 泄漏候选。

### §2.8 Native 内存(Heapprofd — Studio Memory Profiler 看不到这层)

```bash
PACKAGE="<your-app-package>"
OUTPUT=".ai-workspace/diag/$(date +%Y-%m-%d)-heapprofd.pftrace"

adb shell perfetto \
  --config - --txt \
  --out /data/misc/perfetto-traces/heap.pftrace \
  << EOF
duration_ms: 20000
buffers { size_kb: 131072 }
data_sources {
  config {
    name: "android.heapprofd"
    heapprofd_config {
      sampling_interval_bytes: 4096
      process_cmdline: "$PACKAGE"
      all_heaps: true
    }
  }
}
EOF

sleep 22
adb pull /data/misc/perfetto-traces/heap.pftrace "$OUTPUT"
```

Perfetto UI "Heap Profile" 视图,按 retained size 排序找最大 native alloc 来源。常见:Bitmap / ExoPlayer codec buffer / 图片库 cache 无限增长。

### §2.10 主线程 IO 检测(StrictMode)

```bash
adb logcat -c
adb logcat -v time | grep -E "StrictMode|policy violation|DiskRead|DiskWrite|Network"
```

调试期开启:
```kotlin
if (BuildConfig.DEBUG) {
    StrictMode.setThreadPolicy(
        StrictMode.ThreadPolicy.Builder()
            .detectDiskReads()
            .detectDiskWrites()
            .detectNetwork()
            .penaltyLog()
            .build()
    )
}
```

### §2.11 网络瀑布

**Charles Proxy 真机配置(一次性)**:
```
1. Mac:Charles → Proxy Settings → port 8888
2. 真机:Wi-Fi → 修改代理 → 手动 → Mac IP:8888
3. Mac:Help → SSL Proxying → Save Charles Root Certificate → .pem
4. 真机:Settings → Security → Install certificate → 选 .pem
5. Charles:Proxy → SSL Proxying Settings → Host: *
6. Android 7+ 需 network_security_config.xml 信任用户 CA
```

**自动化(OkHttp logcat)**:
```bash
PACKAGE="<your-app-package>"

adb logcat -v time -s OkHttp \
  | tee ".ai-workspace/diag/$(date +%Y-%m-%d)-network-log.txt"
```

### §2.12 过度绘制

```bash
adb shell setprop debug.hwui.overdraw show
adb shell am restart

adb exec-out screencap -p > ".ai-workspace/diag/$(date +%Y-%m-%d)-overdraw.png"

# 完成后关闭
adb shell setprop debug.hwui.overdraw false
```

颜色:蓝(1x)→ 绿(2x)→ 粉(3x)→ 红(4x+)。目标大部分蓝色。

### §2.4 SurfaceFlinger 底层帧延迟

```bash
PACKAGE="<your-app-package>"

# 列出 layer(找目标 Activity)
adb shell dumpsys SurfaceFlinger --list | grep -i <project-name>

LAYER="<your-app-package>/<SampleActivity>#0"
adb shell dumpsys SurfaceFlinger --latency "$LAYER" \
  | tee ".ai-workspace/diag/$(date +%Y-%m-%d)-surfaceflinger.txt"
```

每行 3 个数(纳秒):期望呈现 / 实际呈现 / 提交时间。第 2 列 - 第 1 列 > 16666666ns(16ms)= 掉帧。

区分:App 卡(主线程 spike)vs GPU 合成卡(SurfaceFlinger 侧延迟)。

### §2.13 性能回归防护(Macrobenchmark)

需要 `androidx.benchmark:benchmark-macro-junit4`。

```kotlin
@RunWith(AndroidJUnit4::class)
class HomeFeedScrollBenchmark {

    @get:Rule
    val benchmarkRule = MacrobenchmarkRule()

    @Test
    fun scrollHomeFeedList() = benchmarkRule.measureRepeated(
        packageName = "<your-app-package>",
        metrics = listOf(FrameTimingMetric()),
        compilationMode = CompilationMode.Full(),
        startupMode = StartupMode.WARM,
        iterations = 5
    ) {
        pressHome()
        startActivityAndWait()
        device.findObject(By.text("HomeFeed")).click()
        device.waitForIdle()
        repeat(3) {
            device.swipe(540, 1600, 540, 400, 20)
            device.waitForIdle()
        }
    }
}
```

```bash
./gradlew :benchmark:connectedAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.androidx.benchmark.suppressErrors=EMULATOR \
  --info \
  | grep -E "frameOverrunMs|frameDurationCpuMs|median|P90|P99|PASSED|FAILED"
```

输出读法:
```
frameOverrunMs    median=2.1,  P90=8.3,  P99=24.6   ← P99 > 16ms = jank
frameDurationCpuMs median=8.2, P90=14.1, P99=31.2
```

---

## §3 关键指标读法

| 指标 | 数据来源 | 阈值 |
|---|---|---|
| Janky frames % | `dumpsys gfxinfo` | > 5% 严重 |
| P50/P90/P99 frame time | `dumpsys gfxinfo framestats` | P99 > 16ms = jank |
| Activity Displayed | `adb logcat \| grep Displayed` | 冷启动 < 1.5s 良好 |
| TotalTime | `am start -W` | 同上 |
| TOTAL PSS | `dumpsys meminfo` | < 200MB 良好(中端机) |
| Native Heap | `dumpsys meminfo` 中 Native Heap 行 | 持续增长 = 泄漏 |
| Views: / Activities: | `dumpsys meminfo` 末段 | Activity 数 > 1 = 泄漏 |
| OkHttp Call Time | logcat OkHttp tag | < 800ms WiFi 良好 |

---

## §4 Android 特定性能反模式

- **RecyclerView 滚动卡顿**:`Adapter.onBindViewHolder` 主线程做 IO / 大对象 alloc。修:`prefetchItemCount` + DiffUtil(后台) + 图片库(Coil)异步解码。
- **Bitmap 未 recycle 导致 OOM**:大图直接 `BitmapFactory.decodeFile` 不压缩。修:Coil / Glide + `inSampleSize` + LruCache。
- **Compose 过度 recompose**:lambda 捕获不稳定引用 / `remember` 缺 key / 整个 list 当 key。修:`@Stable` / `@Immutable` annotation + `derivedStateOf` + `key()` 显式标记。
- **SharedPreferences 主线程 commit**:`prefs.edit().commit()` 阻塞主线程。修:`apply()` 异步,或 DataStore。
- **Room 主线程 query**:同步 dao 调用。修:`suspend fun` + Flow + `Dispatchers.IO`。
- **CoroutineScope 错用**:`GlobalScope` 导致泄漏。修:`viewModelScope` / `lifecycleScope`。
- **Choreographer skipped frames warning**:logcat 出现 `Skipped N frames!` = 主线程阻塞 > 16ms × N。
- **冷启动慢**:`Application.onCreate` 做同步 IO / 第三方 SDK 初始化。修:App Startup 库懒加载 / WorkManager 后台。

---

## §5 ANR 诊断(主线程 > 5s)

```bash
# 找 ANR trace
adb shell cat /data/anr/traces.txt | head -200

# 定位 main thread 阻塞点
grep -A 20 'main".*tid=' /data/anr/traces.txt

# bugreport(完整诊断)
adb bugreport /tmp/bugreport.zip
```

修复方向:
- 数据库 query → `suspend` / Flow + `Dispatchers.IO`
- 文件 IO → `Dispatchers.IO`
- 大列表 diff → DiffUtil(background)
- 图片解码 → Coil / Glide(自动 background)
- JNI 调用 → 检查 native 实现是否阻塞

---

## §6 内存泄漏 — LeakCanary

```kotlin
// build.gradle
debugImplementation "com.squareup.leakcanary:leakcanary-android:2.x"
```

```bash
# 监控 LeakCanary 日志
adb logcat -s LeakCanary
```

LeakCanary 自动检测 Activity / Fragment / ViewModel 泄漏,输出 retain cycle 链。

---

## §7 诊断 handoff 示例(摘录字段)

```markdown
## 诊断数据

| 指标 | 数值 | 工具 | 文件 |
|---|---|---|---|
| Janky frames | 42/487 = 8.62% | dumpsys gfxinfo | gfxinfo.txt |
| P99 帧耗时 | 72ms | dumpsys gfxinfo framestats | 同上 |
| 主线程最大 spike | 95ms (Adapter.onBindViewHolder) | Studio CPU Profiler | flame.png |
| TOTAL PSS | 312MB | dumpsys meminfo | meminfo.txt |
| OkHttp 接口 1 | 1.2s 串行 | Charles | network.png |

## Top-3 耗时来源

1. **`Adapter.onBindViewHolder`** — 95ms × 多次(占 60%)
   证据:flame.png 主线程最宽块,Wall Clock = CPU Time → CPU 密集
2. **`SharedPreferences.commit`** — 主线程同步 IO 30ms
   证据:StrictMode logcat policy violation
3. **GET /api/v1/feed** — 1.2s
   证据:Charles Timing tab DNS 200ms / Wait 800ms

## 排除项

- Bitmap 解码:已用 Coil 异步,profiler 不在主线程 → 排除
- Compose recompose:本页是 RecyclerView 不是 Compose → 不适用
```
