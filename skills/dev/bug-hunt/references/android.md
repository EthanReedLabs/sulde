# bug-hunt Android 参考(`mobile-android`)

> 配套 `../SKILL.md`。Android 特定 log / 工具 / 常见 pattern。

## §1 常见排查维度(Android)

| 维度 | 切入点 |
|---|---|
| 生命周期 | Activity / Fragment lifecycle / `onSaveInstanceState` / 配置变更 / process death |
| 状态管理 | MVI Store reduce 分支覆盖 / Flow collect lifecycle / `viewModelScope` |
| 内存 | LeakCanary 报告 / Bitmap recycle / Coil ImageRequest cache |
| 线程并发 | `Dispatchers.IO` vs Main / coroutine cancellation / Channel 背压 |
| 网络数据 | OkHttp interceptor / Retrofit error 处理 / SSE flow 完整性 |
| UI 渲染 | RecyclerView prefetch / View Binding lifecycle / Compose recompose |
| 平台兼容 | Android API level / OEM 定制 / Material Design 版本 |

## §2 拉证据命令

```bash
# logcat 全量 + filter
adb logcat -d > /tmp/full.log
grep -E "AndroidRuntime|<your-app>|FATAL|crash" /tmp/full.log | tail -100

# 内存
adb shell dumpsys meminfo <your-app-package> | head -50

# 帧时间(jank)
adb shell dumpsys gfxinfo <your-app-package> 2>&1 | grep -A 20 "Janky"

# 进程
adb shell pidof <your-app-package>
adb shell ps -A | grep <your-app-package>

# git log -S 反向搜索 symbol
git log -S "{symbol}" --since=30d --oneline -- <relevant-module>/
```

## §3 常见 Bug pattern 速查

| 现象 | 常见根因 |
|---|---|
| 偶发空白页 | Flow cold/hot 错(Cold 在新 collector 时 restart),改 StateFlow |
| 数据不同步 | LocalDB / Network 双源没 single source of truth |
| 列表抖动 | DiffUtil `areItemsTheSame` 错(用 hashcode 而非业务 ID) |
| 长按菜单不响应 | View `clickable=true` 但 `longClickable=false` |
| 横屏 NPE | `onSaveInstanceState` 没保 / process death state 丢 |
| Memory leak | Activity context 被 static / singleton 持有 |
| Coroutine 不取消 | 用了 `GlobalScope`(改 `viewModelScope` / `lifecycleScope`)|

## §4 队友分配示例

3 队友常见分工:

1. **队友 1 — 生命周期 + 状态机**:Read Activity/Fragment + Store + reduceUser/Result 分支,看 lifecycle 与 state transition
2. **队友 2 — 数据流 + 网络**:Read Repository + UseCase + Flow chain,看 cold/hot / error 处理
3. **队友 3 — UI 渲染 + 布局**:Read xml / Compose + ViewBinding,看 recompose 触发 / RecyclerView prefetch
