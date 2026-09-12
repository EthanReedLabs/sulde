# parallel-dev Harmony 参考(`mobile-harmony`)

> 配套 `../SKILL.md`。HarmonyOS 特定公共文件 / 构建命令。

## §1 公共文件白名单

```
build-profile.json5                          # 构建配置入口
oh-package.json5                             # 依赖 / 工程配置(并行改必冲突)
{module}/oh-package.json5                    # 模块依赖
{module}/build-profile.json5                 # 模块构建
{module}/src/main/module.json5               # 模块声明 / Ability 配置
{module}/src/main/resources/base/element/*.json  # 资源(string / color / float)
{module}/src/main/resources/base/profile/main_pages.json  # 路由
commons/coreui/src/main/ets/designtokens/AppColors.ets
commons/coreui/src/main/ets/designtokens/AppTypography.ets
commons/coreui/src/main/ets/designtokens/AppGradients.ets
commons/coreui/src/main/ets/scaffolds/*.ets   # 共享 scaffold
local.properties                              # 本地配置
hvigorw / hvigorw.bat                         # 包装脚本不能改
```

## §2 worktree 模板

```bash
git worktree add -b dev/{alias}/{module} ../<project-harmony>-{slug} develop

cd ../<project-harmony>-{slug}
./hvigorw assembleHap --mode debug
hdc install -r build/default/outputs/default/{hap-file}.hap

cd <project-harmony>
git checkout develop && git merge dev/{alias}/{module} && git branch -d dev/{alias}/{module}
git worktree remove ../<project-harmony>-{slug}
```

## §3 verify 命令

```bash
./hvigorw lint
./hvigorw assembleHap --mode debug
hdc install -r build/default/outputs/default/<hap>.hap
hdc shell aa start -a <ability> -b <bundle>
hdc shell hilog | grep <bundle> > /tmp/log.txt &
sleep 30
grep -iE "fatal|error|crash|abort" /tmp/log.txt | tail -10
```

## §4 Harmony 并行特定 gotcha

- **oh-package.json5 / build-profile.json5**:多 worktree 同时改必冲突,串行
- **module.json5 加 ability**:同 iOS pbxproj,串行加
- **resources/ 共享文件**:多 worktree 同改 string.json 必冲突 → 翻译批改串行
- **DevEco Studio 锁**:多 worktree 同时打开 DevEco 可能锁 .gradle 类似目录 → 命令行 hvigorw 可并行,GUI 一次一个

> 占位说明:v0.2.1 初版。Harmony 工具链更新快,项目接入按 DevEco 版本调整。
