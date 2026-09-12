# perf-diagnose Harmony / 鸿蒙 参考(`mobile-harmony`)

> 配套 `../SKILL.md`。HarmonyOS NEXT(ArkTS / ArkUI)特定 profiler 命令 + 指标读法 + 平台模式。
>
> **占位说明**:本初版基于 v0.2.1,实际接入时按项目情况补充 — DevEco Studio 版本 / SmartPerf-Host 命令 / 鸿蒙真机 OS 版本差异应在 PR 时实测确认。

## §1 工具速查表

| 维度 | 首选工具(GUI) | 自动化方案(命令行) |
|---|---|---|
| CPU / 调用栈 | DevEco Profiler → CPU(Time / Sample) | `hdc shell hiprofiler_cmd` |
| 帧率 / FPS | DevEco Profiler → Frame | `hdc shell hidumper -s SystemUI` |
| 自定义时间线标记 | `@ohos.hiTraceMeter` | 代码插桩 + DevEco Frame |
| 启动时间 | DevEco Profiler → Launch | `hdc shell aa start --measure` |
| 内存分配 | DevEco Profiler → Memory | `hdc shell hidumper --mem <pid>` |
| Native 内存 | DevEco Profiler → Native Memory | hiprofiler_cmd |
| JS 调度 / 微任务 | DevEco Profiler → JS Profiler | DevEco GUI |
| 网络瀑布 | DevEco Network / Charles | `hdc shell hilog \| grep -i http` |
| 系统级 trace | SmartPerf-Host | DevEco 集成或独立工具 |
| 性能回归防护 | hypium / @ohos/hypium benchmark | `hdc shell aa test` |
| 设备状态 | `hdc list targets` | 同 |

启动 DevEco Profiler:
```
DevEco Studio → View → Tool Windows → Profiler
→ 连接真机(hdc list 显示)→ 选 App → 选模板(CPU / Memory / Frame / Launch)
```

---

## §2 按问题类型跑诊断套件

### §2.1 滚动卡顿 / FPS

**DevEco Profiler → Frame**:
```
1. DevEco → Profiler → New session → Frame
2. 真机重现滚动 15s
3. Stop
4. 看 FPS 曲线 + 主线程 / JS 线程 / Render 线程时间轴
5. 截图 → .ai-workspace/diag/{date}-{slug}-frame.png
```

**hidumper(命令行帧率)**:
```bash
PACKAGE="<your-bundle-name>"

# SystemUI dumper 含全局 FPS 数据
hdc shell hidumper -s SystemUI -a "-fps"

# App 进程内 frametime
hdc shell hidumper -s WindowManagerService -a "-a"
```

读法:
- 主线程(ets thread)宽块 > 16ms = 掉帧
- JS thread 长任务 > 16ms = ArkTS 执行阻塞
- Render thread spike = 渲染瓶颈

### §2.2 自定义时间线标记(hiTraceMeter)

```typescript
import hiTraceMeter from '@ohos.hiTraceMeter';

// 区间型
hiTraceMeter.startTrace('loadMoreTemplates', 1);
try {
  await templateRepo.loadMore();
} finally {
  hiTraceMeter.finishTrace('loadMoreTemplates', 1);
}

// 数值型(可生成曲线)
hiTraceMeter.traceByValue('templateCount', templates.length);
```

DevEco Profiler Frame / CPU 视图自动显示这些 trace。

### §2.5 启动时间

```bash
PACKAGE="<your-bundle-name>"

# 测量启动时间(冷启动)
hdc shell aa force-stop "$PACKAGE"
sleep 1
hdc shell aa start -b "$PACKAGE" -a EntryAbility --measure 2>&1 \
  | tee ".ai-workspace/diag/$(date +%Y-%m-%d)-launch.txt"
# 输出含 launchTime / firstFrameTime
```

**DevEco Profiler → Launch**:
- 录制冷启动全过程
- 看 EntryAbility.onCreate / onWindowStageCreate / onForeground 各阶段耗时
- 找异常长的 import / 第三方 SDK 初始化

### §2.7 内存

```bash
PACKAGE="<your-bundle-name>"
PID=$(hdc shell pidof "$PACKAGE" 2>/dev/null)

# 进程级内存
hdc shell hidumper --mem "$PID" \
  | tee ".ai-workspace/diag/$(date +%Y-%m-%d)-mem.txt"

# 关键指标
hdc shell hidumper --mem "$PID" | grep -E "Pss|Heap|Native|Graphics"
```

**DevEco Profiler → Memory**:
- Allocation Profile:对象分配排行
- Heap snapshot diff:两次快照对比找 retain
- JS 内存 + Native 内存分开统计

### §2.10 主线程 / JS 线程阻塞

```bash
PACKAGE="<your-bundle-name>"

# JS thread 长任务日志(hilog tag)
hdc shell hilog | grep -E "long task|jank|frame drop" \
  | tee ".ai-workspace/diag/$(date +%Y-%m-%d)-jstask.log"
```

DevEco JS Profiler:
- Micro task queue 长度
- 单次 task 耗时(> 16ms 即影响渲染)

### §2.11 网络

**Charles 真机配置**:
```
1. Mac:Charles → port 8888
2. 真机:设置 → WLAN → 长按当前网络 → 修改 → 高级 → 代理 → 手动 → Mac IP:8888
3. 安装 Charles CA 证书到鸿蒙设备(系统设置 → 安全 → 加密与凭据 → 安装证书)
4. Charles → SSL Proxying → Host: *
```

**hilog 抓 HTTP**:
```bash
hdc shell hilog | grep -iE "http|net|<bundle-name>" \
  | tee ".ai-workspace/diag/$(date +%Y-%m-%d)-net.log"
```

### §2.13 性能回归防护(hypium)

```typescript
// entry/src/ohosTest/.../PerformanceTest.ets
import { describe, it, expect } from '@ohos/hypium';

export default function PerformanceTest() {
  describe('HomeFeedScrollPerf', () => {
    it('scroll FPS should >= 55', 0, async () => {
      // 启动 App 到 HomeFeed
      // 模拟滚动
      // 通过 hiTraceMeter 抓取 frame data
      // 断言 P99 < 16ms
    });
  });
}
```

```bash
hdc shell aa test -b <bundle-name> -m <module> -s class PerformanceTest
```

---

## §3 关键指标读法

| 指标 | 数据来源 | 阈值 |
|---|---|---|
| FPS(滚动) | DevEco Frame / hidumper -fps | < 55fps = jank |
| 主线程最大 spike | DevEco CPU Profiler | > 16ms = 单帧掉帧 |
| JS thread 单 task | JS Profiler | > 16ms 即阻塞渲染 |
| 启动时间 | `aa start --measure` | 冷启动 < 1.5s 良好 |
| Pss 内存 | `hidumper --mem` | < 200MB 良好(中端机) |
| GPU memory | `hidumper --mem` Graphics 段 | 大图列表注意 |

---

## §4 Harmony 特定性能反模式

- **`ForEach` 缺 keyGenerator**:列表整体重渲。修:`ForEach(items, item => ..., item => item.id)` 提供稳定 key。
- **`LazyForEach` 缺 cachedCount**:滚动时反复 create / destroy。修:`LazyForEach(...).cachedCount(5)` 缓存 5 屏。
- **重计算在 build 函数**:`@Component build()` 内做 IO / 同步计算。修:用 `@State` 缓存 + `aboutToAppear` 异步加载。
- **重 widget 不做边界隔离**:动画 widget 触发父子全部重渲。修:`@Builder` 拆子 + `@Reusable` 复用。
- **同步 IO 在主线程**:文件 / 数据库同步调用。修:`@ohos.taskpool` 派后台任务 + Promise 异步。
- **`@State` 范围过大**:整 Component 重 build。修:状态局部化 + `@Link` / `@Provide` 细粒度。
- **图片不指定尺寸**:`Image(src)` 全分辨率解码。修:`.width(N).height(N)` + `.objectFit(ImageFit.Cover)`。
- **频繁创建 ArkTS 对象**:循环内 `new Xxx()` 触发 GC。修:对象池 / static 缓存。
- **大数据传递跨线程**:`taskpool` 传大对象 serialize 慢。修:用 `@Sendable` 标记 + 引用传递。

---

## §5 性能优化 checklist

- [ ] `LazyForEach` 配 `cachedCount` ≥ 3
- [ ] `ForEach` / `LazyForEach` 提供 keyGenerator
- [ ] 重型计算用 `@ohos.taskpool` 派后台
- [ ] `Image` 显式指定尺寸 + objectFit
- [ ] `@State` 局部化,跨组件用 `@Link` / `@Provide` / `@Consume`
- [ ] 列表 cell 加 `@Reusable` decorator
- [ ] hiTraceMeter 标记业务关键路径,与 Profiler 时间轴对齐
- [ ] Profile / Release 模式实测,不在 Debug 论结论

---

## §6 验证(repair verify)

```bash
PACKAGE="<your-bundle-name>"

# 1. 编译(DevEco / hvigor)
hvigorw assembleHap

# 2. 安装 + 启动
hdc install -r entry/build/default/outputs/default/entry-default-signed.hap
hdc shell aa start -b "$PACKAGE" -a EntryAbility --measure

# 3. 真机操作触达原性能场景

# 4. 跑同一 Profiler session,对比基线
#   - DevEco Profiler Frame → 看 FPS 曲线是否提升
#   - hidumper --mem → 看 Pss 是否回落
```

---

## §7 诊断 handoff 示例(摘录)

```markdown
## 诊断数据

| 指标 | 数值 | 工具 | 文件 |
|---|---|---|---|
| FPS(滚动) | 42fps(应 60+) | DevEco Frame | frame.png |
| 主线程最大 spike | 85ms (FeedItem build) | DevEco CPU | cpu.png |
| JS thread 长任务 | 3 次 > 50ms | JS Profiler | jstask.log |
| Pss 内存 | 320MB | hidumper --mem | mem.txt |
| 启动时间 | 2.4s | aa start --measure | launch.txt |

## Top-3 耗时来源

1. **`FeedItem.build`** — 平均 35ms × 高频
   证据:CPU profiler 主线程最宽块,LazyForEach 缺 cachedCount 反复重建
2. **图片解码** — 全分辨率
   证据:Image 未指定尺寸,大图直接载入
3. **同步文件读** — 主线程 20ms × 多次
   证据:hilog "long task" + CPU profiler 显示在 fileio.readSync

## 排除项

- 网络:接口 < 200ms 不在 jank 时段 → 排除
- Native 内存:稳定 → 排除
```
