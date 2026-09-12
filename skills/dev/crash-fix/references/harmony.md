# crash-fix Harmony 参考(`mobile-harmony`)

> 配套 `../SKILL.md`。HarmonyOS NEXT 特定日志命令 + 崩溃模式 + 验证。

## §1 拉日志命令

### runtime — hdc shell hilog

```bash
# 按 bundle 过滤
hdc shell hilog | grep <bundle_name> > /tmp/hilog.log &
LOG_PID=$!
sleep 30  # 期间触达原崩溃 / 手动操作
kill $LOG_PID
grep -iE "fatal|error|crash|exception|abort|signal" /tmp/hilog.log | tail -60

# 已崩溃时拉最近的 fault log
hdc shell ls /data/log/faultlog/temp/ | head -5
hdc shell cat /data/log/faultlog/temp/{latest-fault-log}.log | head -200

# DevEco Studio 工程的 ohpm 日志(构建期)
hdc shell hilog -t TS | tail -60  # TypeScript runtime
```

### build — hvigorw

```bash
# 构建错误
./hvigorw assembleHap --mode debug 2>&1 | grep -A 3 "ERROR\|error:\|FAILED" | head -60

# Windows
hvigorw.bat assembleHap --mode debug 2>&1 | grep -A 3 "ERROR\|error:" | head -60

# 模块特定
./hvigorw :entry:assembleHap --mode debug 2>&1 | grep -A 3 "error:" | head -40
```

### hang / 卡死

```bash
# hidumper 抓应用 dump
hdc shell hidumper -s <bundle_name> 2>&1 | head -100

# CPU sample
hdc shell hidumper -s WindowManagerService -a "-a" | head -50
```

### 设备信息

```bash
hdc list targets
hdc shell param get const.product.model
hdc shell param get const.product.software.version
hdc shell bm dump -n <bundle_name> | grep versionName
```

## §2 常见崩溃模式(Harmony / ArkTS)

| 异常 | 常见原因 | 检查点 |
|---|---|---|
| `TypeError: Cannot read property X of undefined` | 访问 undefined 属性 | `obj?.field` chaining |
| `TypeError: X is not a function` | 方法名错 / context 丢失 | `this` binding,`bind(this)` |
| `RangeError` | 数组越界 / 递归过深 | `arr[i]` / 递归终止条件 |
| `@Component decorator missing` | 装饰器顺序错 | `@Entry @Component struct` 顺序固定 |
| `State variable type mismatch` | `@State` 类型变化 | 初始化 vs 后续赋值类型一致 |
| `Resource not found: $r(...)` | 资源 ID / 路径错 | `resources/base/element/string.json` |
| `Failed to load module X` | 模块依赖错 | `oh-package.json5` 依赖声明 |
| `JS heap out of memory` | 大对象 / 内存泄漏 | hidumper -m {pid} mem |
| `Navigation path stack overflow` | 路由栈过深 | `router.clear()` 或 `popMode` |
| `Ability lifecycle error` | onWindowStageCreate / onBackground 异常 | abilityStage.ts 实现 |

## §3 架构链路诊断(Harmony ArkUI)

### Component 链路

- **装饰器顺序**:`@Entry @Component struct Foo` 严格顺序,调换报错
- **@State 类型**:初始化类型决定后续可赋值类型
- **`@State` 对象 mutation**:`this.items.push(x)` 不触发 — 用 `this.items = [...this.items, x]`
- **`@StorageLink` 双向**:storage key 名 typo → 无报错但数据不同步
- **`@Provide` / `@Consume`**:跨组件传递,key 必匹配

### Ability 生命周期

- `onCreate` → `onWindowStageCreate` → `onForeground` → `onBackground` → `onDestroy`
- 拿 windowStage 时机:仅 `onWindowStageCreate` 内有效
- 进程被杀(冷启动)后 state 不保留 — 用 AppStorage / 持久化

### Native 桥接(C++ API / NAPI)

```typescript
// ArkTS 调 C++ 模块,错误处理:
try {
  const result = nativeModule.foo(arg);  // 同步
} catch (e: BusinessError) {
  // e.code / e.message
}
```

异步:
```typescript
nativeModule.fooAsync(arg)
  .then(result => { ... })
  .catch((e: BusinessError) => { ... });
```

## §4 责任 Dev 路径前缀

Harmony 项目通常按 feature 分模块,例如:

| 文件路径前缀 | 责任 Dev | 分支前缀 |
|---|---|---|
| `features/home/src/main/ets/` | A | `dev/dev-a/` |
| `features/discover/src/main/ets/` | A | `dev/dev-a/` |
| `features/create/src/main/ets/` | B | `dev/dev-b/` |
| `features/inbox/src/main/ets/` | C | `dev/dev-c/` |
| `features/profile/src/main/ets/` | C | `dev/dev-c/` |
| `commons/coreui/src/main/ets/` | B | `dev/dev-b/` |
| `commons/corenetwork/src/main/ets/` | C | `dev/dev-c/` |

项目本地 mapping 在 `<docs-hub>/page-owner-map.yaml`。

## §5 验证

```bash
# 1. 编译
./hvigorw assembleHap --mode debug

# 2. install + launch
hdc install -r build/default/outputs/default/<hap-file>.hap
hdc shell aa start -a <ability-name> -b <bundle-name>

# 3. 触达原崩溃场景(手动操作)

# 4. 抓 30s hilog,无新 crash
hdc shell hilog -r  # clear buffer
sleep 30
hdc shell hilog -e <bundle_name> | grep -iE "fatal|error|exception|abort" | tail -20
```

验证全过 → handoff `§ verify` 段含上述 4 步证据。

## §6 Harmony 特定修复模式

- **undefined 防御**:`obj.field` → `obj?.field ?? defaultValue`
- **数组越界**:`arr[i]` → `arr.at(i) ?? ...` 或 `if (i < arr.length) ...`
- **`@State` mutation**:`this.list.push(item)` → `this.list = [...this.list, item]`
- **资源引用错**:确认 `resources/base/element/{string,color,media}.json` 内存在该 key
- **路由栈**:`router.pushUrl({ url: 'pages/Foo' })` 失败时检查 `pages/Foo.ets` 在 `main_pages.json` 注册

## §7 hidumper 抓 dump 诊断 hang

```bash
# 全 system dump(大,定向 grep)
hdc shell hidumper > /tmp/hidump.txt 2>&1
grep -A 20 "<bundle_name>" /tmp/hidump.txt | head -100

# 指定 service
hdc shell hidumper -s WindowManagerService > /tmp/wm.txt
```

修复方向:
- 主线程 IO → 用 TaskPool / Worker
- 大数据列表渲染 → LazyForEach + cachedCount
- Image 加载 → 用 ImageKnife 等异步组件
- Promise chain 过长 → 拆 async / await

## §8 ArkTS 类型守卫(避免 TypeError)

```typescript
// ❌ 不安全
function process(value: string | number) {
  return value.toLowerCase();  // 若 number 则崩
}

// ✅ 类型守卫
function process(value: string | number) {
  if (typeof value === 'string') {
    return value.toLowerCase();
  }
  return value.toString();
}
```

> **占位说明**:Harmony 工具链 + ArkTS API 更新较快,本 references/harmony.md v0.2.1 初版基于 API level 11/12 的常见模式。项目实际接入时根据 DevEco Studio 当前版本 + HarmonyOS API level 调整命令版本。
