# code-review iOS 参考(`mobile-ios`)

> 配套 `../SKILL.md`。iOS 特定架构契约 / lint / 常见反模式。

## §1 架构合规 checklist(队友 1)

| 维度 | 检查项 |
|---|---|
| TCA Action 三分类 | View Action 可 `.run`;Result Action 只 `.none` 或 `.send(.delegate)`;Delegate 父 Reducer 处理后 `.none` |
| 模块依赖方向 | Feature 不依赖其他 Feature;只依赖 `Spec`(Port) + `CoreUI` |
| 创建类型模块 | `<FeatureTypeA>` / `<FeatureTypeB>` 等依赖 `CoreUI`,**不依赖 FeatureCreate** |
| AIClient 泛型 | 用泛型 `submit(_ request: CreateRequest)`,**不为每种类型写单独方法** |
| 长时工作流 | 轮询在单个 `.run` 内 `for await` 平铺,**不链式触发新 `.run`** |
| Perception tracking | View 用 `@Perception.Bindable` 必配 `WithPerceptionTracking { ... }`(iOS 16+ fallback) |
| git 身份 | commit author 与 `.sulde-config.yaml: team[]` mapping 一致 |
| 分支命名 | `dev/{alias}/{module-name}` 格式 |
| AI 痕迹 | grep -i `claude\|gpt\|generated\|auto-generated\|llm` → 全 0 |
| commit message | 中文拟人化 |
| `Sources/CoreUI/` 改动 | 必走协调端 task md(scaffold 层敏感) |

## §2 代码质量 / 性能 checklist(队友 2)

| 维度 | 检查项 |
|---|---|
| 内存 | `[weak self]` capture 漏 / Combine `store(in: &cancellables)` / strong reference cycle |
| 主线程 | UIKit / SwiftUI 操作必 main thread(`@MainActor` / `await MainActor.run`) |
| Optional 强解 | `state.xxx!` / `as!` → `guard let` / `as?` |
| TCA Effect 错误处理 | `try await` 必有 catch / 不 silent ignore |
| 资源清理 | `deinit` 移除 KVO / NotificationCenter observer / Combine cancellables |
| URLSession | async / await 正确 cancellation / 超时配置 |
| 大列表 | List / LazyVStack identity 稳定 / `.onAppear` 触底加载 |
| 大图 | Kingfisher / SDWebImage(自动 background decode)/ thumbnail size |
| SwiftUI | body 内不 mutate State / .task vs .onAppear / EquatableView 优化 recompose |
| Combine | `.receive(on: DispatchQueue.main)` for UI update |

## §3 Lint / 静态分析命令

```bash
# SwiftLint
swiftlint

# SwiftFormat(若装)
swiftformat --lint Sources/

# 模拟器 build verify
xcodebuild -project <project>.xcodeproj -scheme <project> \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -skipMacroValidation build 2>&1 | grep -A 3 "warning:\|error:" | head -40

# 反模式 grep(项目特定)
grep -rn '!\s*$\|!\.' Sources/ --include="*.swift" | head -20  # 强解
grep -rn 'try!\|try?' Sources/ --include="*.swift" | head -20  # try 滥用
grep -rn '@Perception.Bindable' Sources/ --include="*.swift" | head -20  # 必配 WithPerceptionTracking
grep -rn 'WithPerceptionTracking' Sources/ --include="*.swift" | wc -l    # 数量对比
```

## §4 项目模块映射(示例,项目可自定义)

> ⚠️ **占位示例 — 替换为你的项目**
> 下方 tree 是某移动创作 app 的 module 结构 + Dev assignment,**仅作格式示例**。你的项目应:
> 1. **优先方式**:在 `<docs-hub>/page-owner-map.yaml` 显式定义本项目实际 module → Dev mapping(coordinator skills 优先读 yaml)
> 2. **备选方式**:用你的 `.sulde-config.yaml: team[]` 替换 `Dev A/B/C`,用实际 module 路径替换 `Sources/FeatureHome/...`

```
Sources/
├── <project>App/             App 壳(AppFeature / MarketConfig)
├── Spec/                     Port 协议(AIService / AuthClient)
├── CoreMVI/                  TCA 扩展(若有)
├── CoreUI/                   ⚠️ 共享 UI 组件 / AppColors / AppTypography(scaffold 敏感)
├── CoreNetwork/              网络层
├── CoreStorage/              存储层
├── CoreUpload/               上传
├── FeatureHome/              首页(Dev A)
├── FeatureDiscover/          发现
├── FeatureDetail/            详情
├── FeatureCreate/            ⚠️ 创建首页
├── <FeatureSampleAgent>/     某创作流
├── <FeatureSampleRealtime>/  实时创作
├── FeatureInbox/             通知(Dev C)
├── FeatureProfile/           我的
└── FeatureAuth/              登录
```

项目本地实际 mapping 在 `<docs-hub>/page-owner-map.yaml`。

## §5 iOS 特定反模式

```swift
// ❌ 强解
state.userId!.uppercased()
// ✅
guard let userId = state.userId else { return .none }

// ❌ try!
let data = try! JSONDecoder().decode(...)
// ✅
do {
    let data = try JSONDecoder().decode(...)
} catch {
    return .send(.parseFailure(error))
}

// ❌ @Perception.Bindable 漏 WithPerceptionTracking
struct FooView: View {
    @Perception.Bindable var store: StoreOf<FooFeature>
    var body: some View { Text(store.title) }  // iOS 16 不刷新
}
// ✅
var body: some View {
    WithPerceptionTracking { Text(store.title) }
}

// ❌ 链式 .run
case .didTapButton:
    return .run { send in
        await send(.foo)  // 父 reducer 拉锁
    }
case .foo:
    return .run { ... }  // 嵌套 .run
// ✅ 单 .run 内 for await 平铺
case .didTapButton:
    return .run { send in
        for await event in client.stream() {
            await send(.event(event))
        }
    }
```
