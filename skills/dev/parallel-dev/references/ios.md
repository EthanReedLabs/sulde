# parallel-dev iOS 参考(`mobile-ios`)

> 配套 `../SKILL.md`。iOS 特定公共文件 / 构建命令。

## §1 公共文件白名单(永不并行改)

```
Info.plist                                  # 主入口配置
*.xcodeproj/project.pbxproj                # ⚠️ Xcode 工程配置(并行改必冲突)
Package.swift                               # SPM 依赖
Sources/CoreUI/AppColors.swift              # 共享色 token
Sources/CoreUI/AppTypography.swift          # 共享字号 token
Sources/CoreUI/AppSpacing.swift             # 共享间距
Sources/CoreUI/AppGradients.swift           # 共享 gradient(协调端管)
Sources/CoreUI/AppRouter.swift              # 全局路由
Sources/CoreUI/AppTopBar.swift              # 标题栏 scaffold
Sources/CoreUI/AdaptiveScaffold.swift       # 适配 scaffold
Sources/CoreUI/AdaptiveStateView.swift      # 三态 scaffold
Sources/{project}App/AppFeature.swift       # App 入口 TCA Reducer
Sources/{project}App/DependencyRegistration.swift  # 全局依赖注册
Sources/Localizable/*.lproj/Localizable.strings  # 多语言
project.yml                                 # 若用 XcodeGen
```

任一文件出现在 ≥ 2 task scope → **串行**。

> ⚠️ `project.pbxproj` 是 iOS 并行最常见的冲突源 — 任何**新加文件**到 module 都会写 pbxproj → 多 worktree 同时加文件 100% 冲突。规则:一次只有一个 worktree 能"新加文件",其他 worktree 只改既有文件。

## §2 worktree 模板

```bash
# 建 worktree
git worktree add -b dev/{alias}/{module} ../<project-ios>-{slug} develop

# Dev 完工后(从 worktree 内,真机 build)
cd ../<project-ios>-{slug}
xcodebuild -project <project>.xcodeproj -scheme <project> \
  -destination 'platform=iOS,id=<UDID>' \
  -allowProvisioningUpdates -skipMacroValidation \
  ENABLE_DEBUG_DYLIB=NO build

# 主协调 merge
cd <project-ios>
git checkout develop
git -c user.name="{name}" -c user.email="{email}" merge dev/{alias}/{module}
git branch -d dev/{alias}/{module}
git worktree remove ../<project-ios>-{slug}
```

## §3 子 agent verify 命令

```bash
# Build(真机,Xcode 26 必加 ENABLE_DEBUG_DYLIB=NO)
xcodebuild -project <project>.xcodeproj -scheme <project> \
  -destination 'platform=iOS,id=<UDID>' \
  -allowProvisioningUpdates -skipMacroValidation \
  ENABLE_DEBUG_DYLIB=NO clean build

# Install + Launch
APP_PATH=$(find ~/Library/Developer/Xcode/DerivedData/<project>-*/Build/Products/Debug-iphoneos \
    -maxdepth 1 -name "<project>.app" -exec stat -f "%m %N" {} \; | sort -rn | head -1 | cut -d' ' -f2-)
ios-deploy --id <UDID> --bundle "$APP_PATH" --justlaunch

# 30s log
idevicesyslog -u <UDID> > /tmp/log.log &
LOG_PID=$!
sleep 30
kill $LOG_PID
grep -iE "fatal|crash|exception|EXC_" /tmp/log.log | tail -10
```

## §4 iOS 并行特定 gotcha

- **pbxproj 冲突**:多 worktree 加文件 100% 冲突;一次只有一个 worktree 新加 / 删 file
- **SPM resolve**:多 worktree 同时跑 `swift package resolve` 会写 `Package.resolved` 冲突 → 派单时讲清"不动 SPM 依赖"
- **CoreUI 改动**:任何 scaffold / token 改动必单 worktree 串行
