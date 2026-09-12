# bug-hunt Harmony 参考(`mobile-harmony`)

> 配套 `../SKILL.md`。HarmonyOS NEXT 特定 log / 工具 / 常见 pattern。

## §1 常见排查维度(Harmony)

| 维度 | 切入点 |
|---|---|
| Ability lifecycle | `onCreate` / `onWindowStageCreate` / `onForeground` / `onBackground` |
| Component | `@State` mutation / 装饰器顺序 / `aboutToAppear` / `aboutToDisappear` |
| 内存 | hidumper -s / DevEco Profiler / 异步 Promise 链 |
| 异步 | Promise / async-await / `taskpool` 错误处理 |
| 网络 | `@ohos.net.http` / `@ohos.net.connection` 状态变化 |
| UI 渲染 | LazyForEach `cachedCount` / `@Reusable` 复用 |
| Native 桥接 | NAPI 错误 / Worker 异常 |

## §2 拉证据命令

```bash
# hilog
hdc shell hilog | grep <bundle_name> > /tmp/hilog.log &

# hidumper(全 system)
hdc shell hidumper > /tmp/hidump.txt

# hidumper 指定 service
hdc shell hidumper -s WindowManagerService > /tmp/wm.txt

# fault log
hdc shell ls /data/log/faultlog/temp/ | head -5
hdc shell cat /data/log/faultlog/temp/{latest}.log

# DevEco Profiler GUI(开发机)
# 通过 DevEco Studio Profiler tab 启动

# git log -S
git log -S "{symbol}" --since=30d --oneline -- features/<relevant-module>/
```

## §3 常见 Bug pattern 速查

| 现象 | 常见根因 |
|---|---|
| @State 数组 mutation 不刷新 | `arr.push` 不触发 → `arr = [...arr, x]` |
| 装饰器报错 | `@Entry @Component struct ...` 顺序固定 |
| Resource not found `$r(...)` | `resources/base/element/*.json` 缺 key / 拼写错 |
| 路由跳转失败 | `pages/Foo.ets` 没在 `main_pages.json` 注册 |
| Ability state 丢失 | 进程被杀冷启动 — 用 `AppStorage` / 持久化 |
| Promise unhandled rejection | `.then(...)` 没 `.catch(...)` |
| LazyForEach 卡顿 | 漏 `cachedCount(N)` / keyGenerator 不稳定 |
| 多 hap 包通信失败 | `@ohos.rpc` / module 间依赖声明 |

## §4 队友分配示例

1. **队友 1 — Component lifecycle + @State**:Read `.ets` Components,看 lifecycle hooks / state mutation pattern
2. **队友 2 — Ability + 跨 module**:Read EntryAbility / 跨 module 调用,看进程 / 进入栈管理
3. **队友 3 — Native / Promise / 异步**:Read NAPI 调用 / Promise chain,看错误处理

> 占位说明:v0.2.1 初版基于 HarmonyOS NEXT API level 11/12 常见 pattern。Harmony 工具链更新快,项目接入时按 DevEco Studio 当前版本补充。
