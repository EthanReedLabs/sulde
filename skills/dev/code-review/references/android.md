# code-review Android 参考(`mobile-android`)

> 配套 `../SKILL.md`。Android 特定架构契约 / lint / 常见反模式。

## §1 架构合规 checklist(队友 1)

| 维度 | 检查项 |
|---|---|
| MVI 两层终止 | `reduceUser` 可返 Command;**`reduceResult` 禁返 Command**(必 `.none`)|
| 模块依赖方向 | Feature 不依赖其他 Feature;只依赖 `core-spec`(Port) + `core-ui` |
| 创建类型模块 | `<sample-agent>` / `<sample-realtime>` 等依赖 `core-ui` 共享组件,**不依赖 feature-create** |
| AIService 泛型 | 用泛型 `submit(CreateRequest)`,**不为每种类型写单独方法** |
| git 身份 | commit author 与 `.sulde-config.yaml: team[]` mapping 一致(`git as-a` / `git as-b` / `git as-c`) |
| 分支命名 | `dev/{alias}/{module-name}` 格式 |
| AI 痕迹 | grep -i `claude\|gpt\|generated\|auto-generated\|llm` → 全 0 |
| commit message | 中文拟人化,无 Phase / 批次 / P0 / emoji / 数字罗列 |
| `.ai-workspace/` | 不应在 git diff 中(已 `.gitignore`)|
| `core-ui/` 改动 | 必走协调端 task md(scaffold 层敏感) |

## §2 代码质量 / 性能 checklist(队友 2)

| 维度 | 检查项 |
|---|---|
| 内存 | Player(Media3 ExoPlayer)未释放 / Coil ImageRequest cache 漏 / Bitmap recycle |
| Player 池 | 项目 3 Player 池策略遵守 / 不在 Adapter 内 new Player |
| 网络 | OkHttp interceptor 完整 / Retrofit `AppError` 统一错误类型 / SSE flow 关闭 |
| 并发 | `viewModelScope` vs `lifecycleScope` 选对 / Flow `collect` 在 lifecycle-aware coroutine / Channel 背压 |
| 资源清理 | `onCleared` / `onTrimMemory` 实现 / `coroutine.cancel()` |
| 重试 | 可重试 error 指数退避 2/4/8s |
| Null safety | `value!!` 强解减少 / `?.let` / `?:` 用 |
| 主线程违规 | Room query 在 main / OkHttp 同步在 main / `Thread.sleep(...)` 在 main |
| 大列表 | DiffUtil 使用 / RecyclerView prefetch / ViewHolder 复用 |
| 大图 | Coil placeholder + crossfade / `Bitmap.Config.RGB_565` 适用 |

## §3 Lint / 静态分析命令

```bash
# Kotlin lint
./gradlew lint
./gradlew ktlintCheck       # 若装了 ktlint plugin

# 全模块编译
./gradlew assembleDebug

# Detekt(若装)
./gradlew detekt

# 反模式 grep(项目特定)
grep -rn "!!\b" feature-*/ core-*/ --include="*.kt" | head -20  # 强解
grep -rn "runBlocking" --include="*.kt"                          # 主线程阻塞
grep -rn "GlobalScope" --include="*.kt"                          # scope 滥用
grep -rn "Thread.sleep" --include="*.kt"                         # 同步 sleep
```

## §4 项目模块映射(示例,项目可自定义)

> ⚠️ **占位示例 — 替换为你的项目**
> 下方 tree 是某移动创作 app 的 module 结构 + Dev assignment,**仅作格式示例**。你的项目应:
> 1. **优先方式**:在 `<docs-hub>/page-owner-map.yaml` 显式定义本项目实际 module → Dev mapping(coordinator skills 优先读 yaml)
> 2. **备选方式**:用你的 `.sulde-config.yaml: team[]` 替换 `Dev A/B/C`,用实际 module 路径替换 `feature-home/...`

```
app/                           主壳(MainActivity / Application)
├── core-mvi/                  MVI 框架(MviStore / CommandExecutor)
├── core-network/              网络层(Retrofit / OkHttp / SSE)
├── core-spec/                 Port 协议
├── core-storage/              存储层
├── core-ui/                   ⚠️ 共享 UI 组件(scaffold 敏感)
├── core-card-playable-state/  播放状态
├── core-upload/               上传
├── core-util/                 工具
├── feature-home/              首页(Dev A)
├── feature-discover/          发现(Dev A)
├── feature-detail/            详情(Dev A)
├── feature-create/            ⚠️ 创建首页 + <sample-agent> + <sample-realtime>(Dev B)
├── feature-inbox/             通知(Dev C)
├── feature-profile/           我的(Dev C)
└── feature-auth/              登录(Dev C)
```

项目本地实际 mapping 在 `<docs-hub>/page-owner-map.yaml`。
