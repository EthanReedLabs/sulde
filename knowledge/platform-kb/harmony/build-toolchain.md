---
doc_id: "platform-kb/harmony/build-toolchain"
container: platform-kb
platform: harmonyos
summary: "构建 / 工具链"
---

# 构建 / 工具链

## A. DevEco env 起手(Win Dev session 每个 Bash call 必跑)

```bash
source /d/HarmonyProject/<project>/scripts/setup-deveco-env.sh
# 期望:✓ DevEco env ready — hvigorw / hdc / ohpm / node 全可用
```

setup 末段可自动 cp `docs-hub/templates/claude-commands/*.md` → `<harmony-project>/.claude/commands/`(本机自建 `/assign` slash command;本机若"只复制模板不装 plugin",IDE 内建 slash 菜单看不到,需自建)。

## B. 工具集真路径(Win)

| 工具 | 路径 |
|---|---|
| hvigorw.bat | `C:\Program Files\Huawei\DevEco Studio\tools\hvigor\bin\hvigorw.bat` |
| hdc.exe | `C:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\toolchains\hdc.exe` |
| ohpm.bat | `C:\Program Files\Huawei\DevEco Studio\tools\ohpm\bin\ohpm.bat` |
| node.exe | `C:\Program Files\Huawei\DevEco Studio\tools\node\node.exe` |
| DEVECO_SDK_HOME | `C:\Program Files\Huawei\DevEco Studio\sdk` |

`hilog` 是设备端 binary(`hdc shell hilog`)。

## C. SDK 版本锁定

- 项目锁定单一 HarmonyOS NEXT SDK 版本(如 6.1.0 / API 14),`00_shared-rules/sdk-version.md` 记锁定值 + 降版原因
- 典型降版原因:目标测试设备 stuck 在某旧 SDK 版本,无法拉到最新 → project compileSdkVersion 跟设备走
- 本机 hvigorw 工具链版本可略高于 project compileSdkVersion(如工具链 6.1.1 + project 6.1.0),build 仍 pass

## D. Signing scheme(多机器协同)

- `build-profile.json5` **每机器 gitignored**,签名物料路径逐机不同
- 模板:`build-profile.json5.template`(committed 进 repo)
- 每机器 cp template → 实际文件,然后 IDE → Project Structure → Signing Configs → **Auto Generate**
- DevEco IDE 自动管理证书 + cert 物料,无需手工填 keystore 路径

## E. hvigorw build

```bash
hvigorw assembleHap --mode module -p product=default --no-daemon
# 期望:BUILD SUCCESSFUL in 8-10s,0 ERROR(WARN 全 pre-existing deprecated 警告可忽略)
```

Build fail → 看 ERROR / Type ERROR(arkts-no-X)→ 对照 `arkts-language.md` 类对应 rule fix。

## F. hdc install / start

```bash
hdc list targets  # 验设备在
hdc install -r entry/build/default/outputs/default/entry-default-signed.hap
hdc shell aa start -a EntryAbility -b com.example.app
hdc shell aa force-stop com.example.app  # 强停
```

## G. hilog filter(详 `real-device-verify.md`)

```bash
hdc shell hilog | grep -E "<app-tag>|<业务 TAG>"
# 看启动日志 / 业务 tag
```

## H. ohpm(包管理)

```bash
ohpm install   # 装项目 dependencies(per oh-package.json5)
# 三方包按 dependency-whitelist 白名单
```

`@kit.*` 鸿蒙官方包不走 ohpm(SDK 内置)。

## I. 新 worktree 起手 3 步

跨 worktree 切 dev branch 后(eg `.worktrees/<slug>/`)**必跑 3 步**,否则 build / install / SDK 接入会报错:

```powershell
cd D:\HarmonyProject\<project>\<harmony-module>\.worktrees\<slug>

# 1. cp build-profile.json5(gitignored,不随 worktree 自动复制)
copy ..\..\build-profile.json5 .

# 2. 装 oh_modules(不在 git;含 native .so 的三方 SDK / 动画库必须装)
ohpm install --all

# 3. 用 env 跑 hvigorw(per build-profile.json5 只 declare product=default,hvigorfile.ts 用 env 取 flavor)
$env:PRODUCT_NAME = 'dev'
.\hvigorw.bat clean assembleHap --mode module
```

漏 #1 → `hvigor 00304035` 报错;漏 #2 → 缺第三方 SDK 的多条 ERROR;`-p product=dev` 参数比 `PRODUCT_NAME=dev` env 不稳。

### ⚠️ 禁 junction `oh_modules` / `.hvigor` 到 spike worktree

**血案**:把主 worktree `oh_modules/` 或 `.hvigor/` junction 到 spike worktree(图省事不重装 dep)→ ArkTS crash `GetRequestedModuleMayThrowError request module is hole`,**native .so 未正确打包进 HAP**(install 后 runtime 拉模块拿不到 native 二进制)。

**根因**:`oh_modules` 含 native .so,junction 不能跨 worktree 共享(.so 跟 worktree 的具体 build cache + 签名物料绑死);`.hvigor` 缓存态在 worktree 间漂移 → clean build 也救不了。

**规则**:
- ✅ `oh_modules/`:每 worktree **独立 `ohpm install --all`**(走本机 cache,~0.4s 装完)
- ✅ `.hvigor/`:每 worktree 各自 clean build,**不 junction 共享**
- ❌ junction `oh_modules` / `.hvigor` 到 spike worktree:**禁**
- ✅ junction `.ai-workspace/`:OK(只是 doc / handoff txt,无 native binary)

## J. Git-bash `hvigorw` `__dirname` 解析陷阱

**症状**:Git-bash 调 `hvigorw` 时 node `__dirname` 解析 `/c/Users/...` 误转 `D:\c\Users\...` → `MODULE_NOT_FOUND`。

**Workaround**(任一):
- ✅ **首选**:用 PowerShell 调 `hvigorw.bat`(per §I + §E + §F)
- ⚠️ Git-bash 兜底:`MSYS_NO_PATHCONV=1 ./hvigorw.bat ...`(避免路径转换)
- ❌ 禁:直接 `./hvigorw` 在 Git-bash 不带 `.bat` + 不带 env

## K. `git worktree add` PowerShell 反斜杠陷阱

**症状**:PowerShell 下 `git worktree add .worktrees\spike-name` 中**反斜杠被 git-for-windows 吞**,实际创成 `.worktreesspike-name`(无分隔符)!

```powershell
# ❌ 反斜杠被吞 → 创建错误目录 .worktreesspike-name
git worktree add .worktrees\spike-name

# ✅ 用正斜杠
git worktree add ".worktrees/spike-name"
```

**规则**:`git worktree add` 路径**必正斜杠 `/`**,无论 Windows / Linux / Mac;不能依赖 PowerShell 反斜杠习惯。

## L. Windows MAX_PATH 超长目录用 robocopy /MIR 空目录删(合并清 worktree)

合并后清 `.worktrees/<task>/` 时,`Remove-Item -Recurse` / `cmd rmdir /s` 报 **"Filename too long"** — npm-style 嵌套(eg `entry/build/.../oh_modules/.ohpm/@xxx+ver/oh_modules/...`)超 260 char MAX_PATH 限制。

### 修法:robocopy /MIR 镜像空目录

```powershell
$empty = New-Item -ItemType Directory -Path "$env:TEMP\empty_$([guid]::NewGuid())" -Force
robocopy $empty.FullName <target_dir> /MIR /NFL /NDL /NJH /NJS /NC /NS 2>&1 | Out-Null
Remove-Item $empty.FullName -Force -Recurse
Remove-Item <target_dir> -Force -Recurse 2>&1 | Out-Null  # 空壳收尾
```

robocopy 内用 Win32 long path API,**不受 MAX_PATH 限**。/MIR 镜像源(空)到 dest → dest 内文件 / 子目录被删。

⚠️ **必先单独删 `.ai-workspace` junction**(`(Get-Item .ai-workspace -Force).Delete()`)— 否则 /MIR 会跟着 junction 删 link 指向的真目录!

### 清 worktree 完整序列

```powershell
# 1. 删 junction(safe pattern)
(Get-Item .worktrees\<task>\.ai-workspace -Force).Delete()

# 2. git worktree remove(可能 fail,继续)
git worktree remove .worktrees/<task>

# 3. git worktree prune 清 records
git worktree prune

# 4. robocopy /MIR empty 物理删
$empty = New-Item -ItemType Directory -Path "$env:TEMP\empty_$([guid]::NewGuid())" -Force
robocopy $empty.FullName .worktrees\<task> /MIR /NFL /NDL /NJH /NJS /NC /NS 2>&1 | Out-Null
Remove-Item $empty.FullName -Force -Recurse
Remove-Item .worktrees\<task> -Force -Recurse 2>&1 | Out-Null

# 5. 删 branch local+remote
git branch -d dev/<dev-id>/<task>
git push origin --delete dev/<dev-id>/<task>
```

通用 Windows 长路径报错(node_modules / .gradle 等)同适用。

---

## M — Win Git Bash MSYS `ohpm install` symlink 让 HAP modules.abc 漏 record

### 症状

App build + install 过,但**真机 cold start 立即 terminate**(~375ms):

```text
E C0xxxx/com.example.app/AppKit: Error message:
cannot find record '&@vendor/native-sdk/Index&<ver>',
please check the request path. '/data/storage/el1/bundle/entry/ets/modules.abc'.
E C0xxxx/com.example.app/AppKit:
  com.example.app is about to exit due to RuntimeError
E C0xxxx/com.example.app/JsEnv:
  submitterStack interface failed, result: -1
```

### 根因

Win Git Bash / MSYS 跑 `ohpm install` 在 `entry/oh_modules/@vendor/<pkg>` 创建 **MSYS 风格 symlink**(target `/d/HarmonyProject/...` 而非 Windows-native junction `D:\HarmonyProject\...`)。

hvigorw(Java native)Windows 路径 + MSYS symlink 解析不一致 → HAP `ets/modules.abc` 漏 `&@pkg/Index&ver` record body。

### 诊断 signal

| signal | meaning |
|---|---|
| `cannot find record '&@pkg/Index&ver'` | modules.abc 中有 import request,但没可加载 record body |
| `JsEnv: submitterStack interface failed` | JS VM crash path;常伴随 abc record missing |
| cold start `~375ms` terminate | app icon tap / aa start 立刻退出,**不是 page 逻辑崩溃** |
| compile/build success 但 device crash | classic build-time vs runtime mismatch |
| `cd entry && ohpm install` Git Bash 内重装无效 | 同 MSYS symlink |

### 验 HAP modules.abc 真值

```bash
unzip -p entry/build/default/outputs/default/entry-default-signed.hap ets/modules.abc \
  | strings | grep -i <pkg>
```

期望含 exact `&@pkg/Index&ver` record body;若无 → MSYS symlink 问题。

### 修法 ABC

**修法 A**(根治):用 `cmd.exe` / PowerShell **native** `ohpm install`,让 hvigorw 见 Windows-native junction:
```cmd
:: cmd.exe
cd /d D:\HarmonyProject\<project>\<harmony-module>
ohpm.bat install
cd entry
ohpm.bat install
```

verify junction:`dir /AL entry\oh_modules\@vendor`(应显 `<JUNCTION>` 类型而非 MSYS)。

**修法 B**(临时 unblock):删外部 HAR 静态依赖,本地 stub 整模块 facade,保 API sig 不 crash。
- ⚠️ 仅当根治 blocker 时用,**显标 Phase 2 cleanup ADR + memory**

**修法 C**(Phase 2 根治):重建 `entry/oh_modules`,校 `.ohpm` + top-level package 结构,恢复 SDK,再 revert stub。

### 派单 instruction 必预警

```markdown
- ❌ 遇 `cannot find record` / modules.abc 漏 record / 外部 SDK 缺失
  → handoff §upgrade 报根因 + 候选修法 ABC,等协调端裁决
- ❌ 禁擅自 stub 整模块解外部 dep / build 问题
- ✅ 同 bug 2 次失败 invoke `superpowers:systematic-debugging`
```

---

## N Worktree provisioning(Win MAX_PATH + junction oh_modules + ArkTS 缓存)

新建 `.worktrees/<slug>/` 后**直接跑 `hvigorw assembleHap` 启动 → 黑屏 `cannot find record` 类崩溃**。两层根因 + Win 特定 teardown 坑:

### N.1 根因 1:`oh_modules` 用 MSYS symlink → ArkCompiler 不写 modules.abc record

- 详 §M(ohpm MSYS symlink HAP modules.abc record 漏诊断)
- worktree 自带 fresh checkout 无 `oh_modules`,Dev 若 Git Bash 内 `ohpm install` 会跑 MSYS symlink → 重蹈 §M 覆辙
- **修法**:`cmd.exe` / PowerShell native `ohpm.bat install`(per §M 修法 A)

### N.2 根因 2:`hvigorw clean` 不清 ArkTS 增量缓存

- `.hvigor/` + `entry/build/` 含 ArkTS 编译增量缓存,主 worktree 与 task worktree 共用 git refs 但 build artifact 独立
- 若 task worktree fresh checkout 后 build,可能命中"stale module record" → cannot find record / class not found
- **修法**:首次 build 前 `rm -rf .hvigor entry/build`(hvigorw clean 不够)

### N.3 Win MAX_PATH(worktree teardown 阶段)

- `git worktree remove` 撞 Windows MAX_PATH(`oh_modules` 深嵌套 path > 260 char)→ `Invalid argument`
- **修法**:
  1. `bash rm -rf .worktrees/<slug>/oh_modules entry/oh_modules`(MSYS 不受 MAX_PATH 限)
  2. `git worktree prune`(强制 deregister)
  3. 残留空目录被 DevEco IDE node/java cwd 锁 "Device or resource busy" 时**放空 stub dir 不删**,功能无影响

### N.4 Dev 首次 worktree 起 build 推荐 recipe

```bash
cd D:/HarmonyProject/<project>/<harmony-module>
git worktree add .worktrees/<slug> -b dev/<dev-id>/<slug> develop   # 已存在报错可忽略
cd .worktrees/<slug>

# 1. 清增量缓存(避 N.2 cache 串)
rm -rf .hvigor entry/build

# 2. native ohpm install(避 N.1 MSYS symlink)— cmd.exe / PowerShell 跑:
#   cd /d D:\HarmonyProject\<project>\<harmony-module>\.worktrees\<slug>
#   ohpm.bat install
#   cd entry && ohpm.bat install

# 3. 起 claude
claude
```

### N.5 自动化脚本

可把 N.1+N.2+N.4 三步封进 `scripts/init-worktree.sh`,Dev 起手优先用脚本替代手敲。

### 派单 instruction 必预警

```markdown
- ❌ 新 worktree 启动黑屏 / cannot find record → 跑 init-worktree.sh 或手动走 N.4 recipe
- ❌ teardown 时撞 MAX_PATH → 走 N.3 三步
- ✅ 同 bug 2 次失败 invoke `superpowers:systematic-debugging`
```
