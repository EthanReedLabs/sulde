# code-review Harmony 参考(`mobile-harmony`)

> 配套 `../SKILL.md`。HarmonyOS 特定架构契约 / lint / 常见反模式。

## §1 架构合规 checklist(队友 1)

| 维度 | 检查项 |
|---|---|
| Component 装饰器 | `@Entry @Component struct Foo` 顺序固定 |
| @State mutation | 数组 / 对象 mutation 必整体替换:`arr = [...arr, x]` |
| Ability lifecycle | onCreate / onWindowStageCreate / onForeground / onBackground 不阻塞 |
| 模块依赖 | features/X 不依赖 features/Y;依赖 commons/* |
| Resource 引用 | `$r('app.{type}.{key}')` 必存在 `resources/base/element/*.json` |
| 路由注册 | `pages/Foo.ets` 必在 `main_pages.json` 注册 |
| oh-package.json5 | 依赖版本固定 |
| git 身份 + 分支 + AI 痕迹 | 同其他 stack |
| commons/coreui 改动 | 必走协调端 task md |

## §2 代码质量 / 性能 checklist(队友 2)

| 维度 | 检查项 |
|---|---|
| 内存 | hidumper -s 验内存增长 / Promise 链泄漏 / Worker close |
| Promise | 必 .catch 或 try/await/catch / unhandled rejection 警示 |
| 主线程 | UI 操作不阻塞 / 重活转 TaskPool |
| 大列表 | LazyForEach + cachedCount + 稳定 keyGenerator |
| 图片 | 占位 alt + 异步加载 / 大图 thumbnail |
| ArkTS 类型 | typeof / instanceof 类型守卫;`as` 转换前 verify |
| Native(NAPI) | try/catch on BusinessError / 异常码统一 |
| @State 类型 | 初始化类型不可改 |

## §3 Lint / 静态分析命令

```bash
# hvigor lint
./hvigorw lint
# Windows: hvigorw.bat lint

# 编译验证
./hvigorw assembleHap --mode debug

# 反模式 grep
grep -rn 'push(' features/ commons/ --include="*.ets" | head -10    # @State 数组 mutation
grep -rn '\.then(' features/ commons/ --include="*.ets" | head -10  # Promise 无 catch?
grep -rn 'as ' features/ commons/ --include="*.ets" | head -20       # 类型转换
```

## §4 项目模块映射

Harmony 典型分包:

```
{project}/
├── entry/                  入口 module
│   └── src/main/ets/
│       ├── entryability/   EntryAbility.ets
│       └── pages/          路由页(Index.ets / 等)
├── features/
│   ├── home/               首页(Dev A)
│   ├── discover/
│   ├── create/             创建(Dev B)
│   ├── inbox/
│   └── profile/            我的(Dev C)
└── commons/
    ├── coreui/             共享 UI / token
    ├── corenetwork/
    └── corestorage/
```

## §5 Harmony 特定反模式

```typescript
// ❌ @State 数组 mutation 不刷新
@State items: Item[] = []
this.items.push(newItem)            // 不触发刷新

// ✅
this.items = [...this.items, newItem]


// ❌ Promise 无 catch
foo().then(result => { /* use */ })  // unhandled rejection

// ✅
foo()
  .then(result => { /* use */ })
  .catch((e: BusinessError) => { /* handle */ })


// ❌ 装饰器顺序错
@Component @Entry struct Foo  // 报错!

// ✅
@Entry
@Component
struct Foo

// ❌ 资源引用 typo
Text($r('app.string.hello_wrold'))  // 资源不存在 → 运行时崩

// ✅ 先 grep resources/base/element/string.json verify 该 key 存在
```

> 占位说明:v0.2.1 初版基于 HarmonyOS NEXT API level 11/12 典型项目。Harmony 工具链 + ArkTS 规范更新快,项目接入按 DevEco Studio 当前版本补充。
