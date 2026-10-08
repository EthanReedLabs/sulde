---
doc_id: "work-model/verify-build"
container: work-model
platform: none
summary: "iOS 与 Android 通用语义,平台命令分别列;launch 与采集证据须核对渲染真值与 summary 落盘,不能只看 PID/exit code。"
related: [work-model/offline-fake-device-cli-testing, ap-0048, work-model/final-backup-before-migration-cutover, work-model/git-worktree-content-evidence-materialization]
sedimentation_schema: 2
problem_type: workflow
evidence_status: verified
---

# 验证流程:simulator/真机 install 必含显式 5 步(三端共享)

> iOS 与 Android 通用语义,平台命令分别列。作为唯一真值。
> 占位约定:`<AppName>`(scheme / .app 名)、`<bundle.id>`(应用包名)、`<UDID>`(真机标识)、`<git-name>` / `<git-email>`(Dev 提交身份)。

## 问题原型

任务只证明源码能编译，或只看到 install/launch 命令退出 0，就宣布设备验收完成；实际设备可能
仍运行旧包、进程启动即退、截图停在主屏，失败路径甚至没有 summary，后续无法区分未执行与失败。

## 根因与证据

构建、产物选择、安装、启动、前台渲染和证据归档是独立边界。已观察到 worktree 构建产物与主
目录安装源不一致、按目录顺序选中旧 `.app`、launch 返回 PID 后立即崩溃、采集脚本在 build
失败处直接退出而未落 summary。显式五步、产物摘要/mtime、前台复核和无条件 summary 能分别
关闭这些缺口；单个 `BUILD SUCCESS` 或 exit 0 无法替代整条链。

## 适用边界

- 适用于 iOS、Android、HarmonyOS 的设备或 simulator 交付验证；平台命令不同，证据语义相同。
- 纯编译门可明确声明 `compile-only`，但不得升级为安装、启动或功能验收通过。
- 首次启动/清状态场景需要 uninstall；保留账号或历史数据的覆盖安装场景不得机械卸载。
- 缺目标平台或真实设备时应记录 deferred/unobserved，不用合成测试冒充 live canary。

## 路由正例

- **输入**：构建成功且 launch 打印 PID，但截图是系统主屏，报告仍写真机通过。
- **预期**：apply
- **原因**：启动信号没有绑定前台存活和目标渲染，属于典型的分层证据误升格。
- **来源**：observed

## 路由反例

- **输入**：任务明确只要求编译门，并如实报告未安装、未启动、未做设备验收。
- **预期**：skip
- **原因**：声明范围与证据范围一致，没有把 compile-only 伪装成 live pass。
- **来源**：constructed

## 执行合格例

- **做法或输出**：冻结构建摘要后显式 install/launch，复核前台进程与目标截图，任何失败都落 summary 并非零。
- **预期**：pass
- **原因**：产物、设备、进程、渲染和失败证据全部绑定同一 run，能够独立复核。
- **来源**：observed

## 执行失败例

- **做法或输出**：只保存 `BUILD SUCCESS`、PID 和一张未检查内容的截图，采集异常时直接退出。
- **预期**：fail
- **原因**：旧产物、启动即退和空证据目录都可能被错误解释为成功。
- **来源**：observed

---

## 铁律

**`xcodebuild build SUCCESS` / `./gradlew assembleDebug` SUCCESS ≠ simulator 装的是新 App**。

- 尤其 Dev 在 worktree 跑 build → DerivedData 在 worktree 内,**主目录 simulator 装的是旧 App**
- App 已在前台跑 → 新装不会自动重启进程,需显式 launch
- 测 reset 状态(如首次启动引导)需 uninstall 清 UserDefaults / SharedPreferences

---

## 5 步流程(必含,缺一不合格)

### Step 1 — uninstall 旧 App(若需 reset UserDefaults / 测首次启动)

| 平台 | 命令 |
|---|---|
| iOS | `xcrun simctl uninstall booted <bundle.id>` |
| Android | `adb uninstall <bundle.id> 2>/dev/null \|\| true` |

### Step 2 — boot simulator / 真机连接(若 shutdown 状态)

| 平台 | 命令 |
|---|---|
| iOS | `xcrun simctl boot '<某 iPhone 型号>' 2>/dev/null \|\| true` + `xcrun simctl list devices booted` |
| Android | `adb devices`(确认设备 connected) |

### Step 3 — clean build(强制走主目录 DerivedData / build 目录,不用 worktree cache)

iOS:
```bash
xcodebuild -project <AppName>.xcodeproj -scheme <AppName> \
    -destination 'platform=iOS Simulator,name=<某 iPhone 型号>' \
    -skipMacroValidation \
    clean build 2>&1 | tail -50
```

Android:
```bash
./gradlew clean assembleDebug 2>&1 | tail -30
```

记录 `** BUILD SUCCEEDED **` / `BUILD SUCCESSFUL` 行。

### Step 4 — install 显式跑(虽 -destination 通常自动 install,显式跑保险)

iOS(**强制按 mtime 选最新 .app**,反模式:选到旧 hash):
```bash
# 按 mtime 倒排选最新 .app,绝不用 `find ... | head -1`(目录顺序非时间序,可能拣到 N 天前旧包)
APP_PATH=$(find ~/Library/Developer/Xcode/DerivedData/<AppName>-*/Build/Products/Debug-iphonesimulator \
    -maxdepth 2 -name "<AppName>.app" -exec stat -f "%m %N" {} \; 2>/dev/null \
    | sort -rn | head -1 | cut -d' ' -f2-)

# 兜底:若 DerivedData 路径无结果(scheme 不同),用 -showBuildSettings 取权威路径
if [ -z "$APP_PATH" ]; then
    DERIVED_DATA=$(xcodebuild -project <AppName>.xcodeproj \
        -scheme <AppName> -showBuildSettings 2>/dev/null \
        | awk -F= '/ BUILT_PRODUCTS_DIR /{gsub(/ /,"",$2); print $2}' | head -1)
    APP_PATH="$DERIVED_DATA/<AppName>.app"
fi

ls -lah "$APP_PATH"
xcrun simctl install booted "$APP_PATH"
```

Android:
```bash
ls -lah app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

**记录 .app / .apk 时间戳必须是今天**,若是几天前 = 选到旧 hash → 排查后重跑。

**iOS verify 任务跑完后清理旧 DerivedData hash**(防止下次又拣到旧的):
```bash
# 保留最新一份 <AppName>-<hash> 目录,删其余
ls -dt ~/Library/Developer/Xcode/DerivedData/<AppName>-*/ 2>/dev/null | tail -n +2 | xargs rm -rf
```

### Step 5 — launch 新 App 进程 + 截图归档

iOS:
```bash
xcrun simctl launch booted <bundle.id>
sleep 3
xcrun simctl io booted screenshot .ai-workspace/screenshots/{slug}/01-{state}.png
```

Android:
```bash
adb shell am start -n <bundle.id>/.SplashActivity
sleep 2
adb shell screencap -p /sdcard/01.png
adb pull /sdcard/01.png .ai-workspace/screenshots/{slug}/01-{state}.png
adb shell rm /sdcard/01.png
```

---

## launch 成功的判据:PID 不是证据(补充)

`simctl launch` / `am start` 返回的 PID、以及 `devicectl process launch` 的 exit code 0,
**只证明进程被创建,不证明 App 前台渲染成功**。进程可能启动后立即 crash、卡在
splash、被系统挡回主屏,而 PID 已经打印、退出码已经是 0。

**判据必须落在渲染真值上,至少满足两条**:

1. **截图内容核对**:截图停在系统主屏 / 桌面 / 空白页 = launch 失败,不是
   "截图已归档 ✅"。归档前必须核对截图里出现的是被测 App 的目标界面
   (可用 OCR、像素差、或人工目视),而不是仅确认文件存在、大小非零。
2. **前台进程复核**:截图后再查一次进程是否仍存活且在前台
   (iOS `xcrun simctl spawn booted launchctl list | grep <bundle.id>` /
   真机 `idevicedebug` 保持运行观察输出;
   Android `adb shell dumpsys activity activities | grep mResumedActivity`)。
   launch 后 3 秒进程消失 = 启动即 crash,按 crash 路径抓日志,不得记为通过。
3. **stdout/stderr 内容核对**:`idevicedebug` 等工具打印 `ERROR` 时退出码仍可能为 0,
   验收必须读输出内容而非只看退出码(见下文 "launch 工具铁律")。

**判定线**:验证段若只记录 "launch 返回 PID xxxxx" + "截图已保存" 而无截图内容
核对与前台进程复核 → 该轮 launch 证据不成立,不得据此声明功能可用。

---

## 采集脚本纪律:失败路径也必须落 summary 证据

验证/采集脚本(build → install → launch → 截图 → 汇总)常见写法是
"build 失败就 `exit 1`",结果 summary / 证据文件根本没生成 —— 事后只看到
证据目录为空,无法区分 "没跑" 与 "跑了但 build 挂了"。

**规则:summary 落盘是脚本的无条件收尾动作,不是成功路径的专属步骤。**

- 用 `trap` / `finally` / `defer` 把 summary 写入挂在退出路径上,任何 `exit` 都经过它
- summary 必含:`status`(success/build_failed/install_failed/launch_failed/no_render)、
  失败发生的步骤名、该步骤的原始输出尾部(如 `tail -50`)、时间戳、设备标识
- 失败轮次的证据**保留不覆盖**——它证明的是失败路径的行为,与成功轮次同等重要
- 空证据目录必须能被上游判为 "脚本未执行完",因此脚本**不得**在写 summary 前
  静默退出;若连 summary 都写不出,退出码要与业务失败区分开

骨架:

```bash
SUMMARY="$EVIDENCE_DIR/summary.json"
STATUS="unknown"; STEP="init"; DETAIL=""

finish() {
    mkdir -p "$EVIDENCE_DIR"
    printf '{"status":"%s","failed_step":"%s","detail":%s}\n' \
        "$STATUS" "$STEP" "$(printf '%s' "$DETAIL" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
        > "$SUMMARY"
}
trap finish EXIT

STEP="build"
if ! BUILD_OUT=$(build_cmd 2>&1); then
    STATUS="build_failed"; DETAIL=$(printf '%s' "$BUILD_OUT" | tail -50); exit 1
fi
# ... install / launch / 截图,每步同样先设 STEP 再执行
STATUS="success"
```

**判定线**:采集脚本存在任何 `exit` 路径绕过 summary 写入 = 不合格;
证据目录为空即视为该轮验证未完成,不得按 "没发现问题" 处理。

---

## 验证脚本的双通道契约：summary 与退出码必须一致

summary 负责解释，进程退出码负责控制上游。两者缺一不可，也不得互相矛盾：

- 只有所有验收条件都满足时才返回 0；`build_failed`、`launch_failed`、截图停在主屏、
  目标输出为空或关键指标缺失都必须返回非 0。
- 非 0 之前仍由上节的无条件收尾写出 summary。不能为了留下证据而把失败吞成 0，也
  不能只返回非 0 却留下空证据目录。
- 上游先按退出码阻断，再读取 summary 定位根因；禁止用“命令跑完了”或“有截图文件”
  替代验收结论。
- 写脚本时先用 fake CLI/fixture 补失败路径自测：至少覆盖子命令非 0、输出为空、截图为
  非目标页和 summary 写入失败，逐项断言最终退出码与 `status` 一致。

**判定线**：summary 为失败但退出 0，或验收证据无效却退出 0，均属于误放行门禁。

---

## 昂贵构建前先跑同配置轻量 preflight

签名、设备、模型和磁盘等确定性前置条件，不应等几分钟构建后才暴露。把能在数秒内判定
的条件放在 build/install 前，并确保它们检查的正是后续命令将使用的配置：

1. iOS 检查目标设备、证书有效期、team/bundle id、provisioning profile 与 entitlement
   匹配；Android/HarmonyOS 检查设备、签名物料和目标 variant。
2. 端侧模型检查路径、精确字节数/哈希、运行时兼容信息与可用空间，完整性规则引用
   `tech-docs/端侧大模型文件必须做内容哈希校验` 的同一真值。
3. preflight 失败立即非 0，summary 写明确切缺项和修复入口；不得继续昂贵步骤，也不得把
   “未检查到”写成 PASS。
4. 用缺证书、过期 profile、缺模型、错误哈希和设备离线等 fixture 做负向自测；只有
   preflight 通过才进入 build。

preflight 只证明前置条件就绪，不替代构建、安装、启动与渲染验收。

---

## Why 5 步缺一不合格

- `xcodebuild build` / `./gradlew assembleDebug` 只跑编译;若 simulator 已装同 bundle id 的旧版,**simulator 用旧 cache**(必须 uninstall)
- worktree 跑 build → DerivedData / build 目录在 worktree 路径下;主目录 simulator/真机 用主目录构建产物 → **不一致**
- App 已在前台跑 → 新装不会自动重启进程,需 `xcrun simctl launch` / `adb shell am start`
- 测试 reset 状态(如首次启动引导)需 uninstall 清 UserDefaults / SharedPreferences

---

## ✅ 正确

1. **task md simulator/真机验证段必含 5 步**(reset / boot / build / launch / 截图),不只 `xcodebuild build` / `assembleDebug`
2. **测 "首次启动" / reset 类场景**:必加 uninstall(清 UserDefaults / SharedPreferences)
3. **handoff 内验证截图归档**:必带 reset 后的 fresh launch 截图,不只 build SUCCESS 声明;截图须核对内容而非仅核对文件存在
4. **用户报"和没改一样"时**,先怀疑这点 — 让用户跑完整 install + launch 流程,而不是直接派新 task
5. **写采集脚本时先写 `trap` 收尾**,再写业务步骤 — 保证任何失败路径都留下 summary

---

## 判定线

任务书 simulator/真机验证段缺 install + launch = 不合格(只 `xcodebuild build` / `assembleDebug` 不够);
launch 只凭 PID / exit code 判成功、截图不核对内容 = 证据不成立;
采集脚本失败路径不落 summary = 不合格。

---

## 实例

- 某次用户报"和没改一样",查 git log Dev 实际改了数百行 + grep test 全过 + 节点对照,**真因是用户 simulator 装着旧 App**(没重 install)
- 某次用户报"跑的都是过往版本",查 DerivedData .app 时间戳是几天前,develop 已更新 → 派 fresh install verify task
- 某次 launch 返回了 PID 且截图已归档,复核发现截图停在系统主屏 — App 启动后即退,该轮"验证通过"作废
- 某次采集脚本在 build 失败处直接 `exit 1`,证据目录全空,事后无法区分"未执行"与"build 挂了"

## 消费与防复发

- task、runbook、采集脚本和 handoff 只链接本文件的五步语义，避免复制多套漂移命令。
- 每轮证据绑定 commit/build digest、设备 ID、包 ID、产物路径与时间；失败轮次保留且不被成功轮覆盖。
- fake CLI 回归覆盖构建非零、产物为空/过期、安装失败、launch 假成功、截图非目标页和 summary
  写入失败；真实宿主验收只在相应设备与权限边界可用时执行。

---

# iOS 真机验证(iOS task md 默认真机)

iOS 代码修改完**默认走真机验证**(不再 simulator),原因:接近发版前真机覆盖更真实(网络 / token / 推送 / 性能 / Charles 抓包);simulator 不能测 push / Apple Pay / 真机性能等。

这条要求必须同时登记到 runbook、当前 plan/backlog 与交付 handoff 等上下文恢复入口；
只写在临时任务书里，压缩、换会话或接班后就会退回 simulator。各入口只链接本节作为
唯一命令真值，不复制一套可能漂移的脚本。simulator 仍限于本文“例外”列出的纯逻辑、
单元测试和仅编译验证；Run 与实际功能验收必须真机。

## 真机 5 步(iOS task md 验证段标准流程)

### Step 1 — 列真机 + UDID

```bash
xcrun devicectl list devices  # 列出 paired 真机 + UDID + name + state
```

记 UDID(后续 step 用)+ 确认真机 `state: connected`。

若 `ios-deploy` 枚举为空、打印告警或退出码异常，不要立即判设备离线并让用户反复插拔。
用构建系统看到的 destination 交叉验证：

```bash
xcodebuild -workspace <AppName>.xcworkspace -scheme <AppName> -showdestinations
```

`xcodebuild` 能列出目标而 `ios-deploy` 不能时，问题属于工具枚举/会话层；设备连接结论至少
需要两个独立入口一致，单个第三方工具的退出码不是设备离线真值。

### Step 2 — uninstall 旧 App(若需 reset / 测首次启动)

```bash
xcrun devicectl device uninstall app --device <UDID> <bundle.id>
# 或真机 Settings → General → iPhone Storage → <AppName> → Delete App
```

### Step 3 — clean build for device(强制加 `ENABLE_DEBUG_DYLIB=NO`)

```bash
xcodebuild -project <AppName>.xcodeproj -scheme <AppName> \
    -destination 'platform=iOS,id=<UDID>' \
    -allowProvisioningUpdates \
    -skipMacroValidation \
    ENABLE_DEBUG_DYLIB=NO \
    clean build 2>&1 | tail -50
```

⚠️ **必加 `ENABLE_DEBUG_DYLIB=NO`**(实证):
- 新版 Xcode 的 Debug-iphoneos build **默认注入 `__preview.dylib` + `<AppName>.debug.dylib`**(SwiftUI Previews 框架)
- 旧 iOS 真机 dyld 加载 `__preview.dylib` 失败 → **SIGTRAP 启动数毫秒 crash**(`bug_type 309 + EXC_BREAKPOINT`)
- simulator build 没问题(simulator dylib 加载机制不同)
- `ENABLE_DEBUG_DYLIB=NO` 关闭 debug dylib 注入,主二进制变独立完整(stub → 完整二进制)
- 实证案例:旧 iOS 真机 launch 多次 crash,加此 flag 后修复

⚠️ **禁止在 CLI 全局覆盖 `PRODUCT_BUNDLE_IDENTIFIER`**：命令行 build setting 会作用于所有参与构建的 target，使多个 SPM 资源 bundle 获得相同 `CFBundleIdentifier`；系统按 bundle id 缓存 asset catalog 后，可能跨 bundle 错误命中或报告资源不存在。临时验证包只修改 App target 自身的 build configuration / `.xcconfig`，构建命令仅传必要的签名设置；构建后确认各资源 bundle 标识唯一。

记录 `** BUILD SUCCEEDED **`。

### Step 4 — install app to device(mtime 选最新 .app)

```bash
APP_PATH=$(find ~/Library/Developer/Xcode/DerivedData/<AppName>-*/Build/Products/Debug-iphoneos \
    -maxdepth 2 -name "<AppName>.app" -exec stat -f "%m %N" {} \; 2>/dev/null \
    | sort -rn | head -1 | cut -d' ' -f2-)

ls -lah "$APP_PATH"  # 确认 mtime 是今天(防选旧包)
xcrun devicectl device install app --device <UDID> "$APP_PATH"
```

注意:**`Debug-iphoneos`**(不是 `Debug-iphonesimulator`)。

### Step 5 — launch + 截图归档

```bash
xcrun devicectl device process launch --device <UDID> <bundle.id>
sleep 3
xcrun devicectl device captureScreenshot --device <UDID> .ai-workspace/screenshots/{slug}/01-{state}.png
```

或用 Apple Devices.app(macOS 内置)/ idevicescreenshot(libimobiledevice)截屏。

**截图归档后必须核对内容**:停在系统主屏 / 锁屏 / 空白 = launch 失败,按上文
"launch 成功的判据" 复核前台进程与 stdout,不得只凭 PID 与文件存在记为通过。

### launch 工具铁律：安装与持进程启动分离

当 `devicectl` 不可用而切换到 usbmuxd 工具链时：

- `ios-deploy --justlaunch` 会在启动后 detach，目标进程可能随之退出；它不能作为“App 已稳定留在前台”的验证证据。
- 安装使用 `ios-deploy --id <UDID> --bundle "$APP_PATH" --no-wifi --justinstall`；需要持续运行、截图或观察日志时，使用 `idevicedebug -u <UDID> run com.example.app.debug` 并在验证期间保持命令运行。
- `ios-deploy -L/--justlaunch` 路径会触发 safe quit，日志里的 PID 可能恒为 `-1`；`-d`
  保持 LLDB 会话可作临时诊断，但规范验收仍统一用 `idevicedebug run`，避免两套启动真值。
- Debug 包的 bundle id 必须使用 `.debug` 后缀；Release 包才使用生产 bundle id。
- `idevicedebug` 即使打印 `ERROR`，进程退出码仍可能为 0。验收 launch 必须检查标准输出/错误输出中是否有错误，禁止只凭 exit code 判成功。
- 调试器结束会话时可能记录 `signal 9`；它单独不能证明 App 自发崩溃。只有在 held launch
  期间 PID 消失，并有 probe 未完成或独立 crash report 支持时，才判应用崩溃。PID、probe
  文件与 crash report 至少两类证据一致；teardown 后的单行信号只标为调试器事件。

### 真机 probe 参数使用预置文件，不依赖 idevicedebug 注入

`idevicedebug` 没有跨版本可靠的 `-e` 环境变量注入语义，bundle id 后的 `--flag` 也可能
继续被它当作自身 option。需要给 debug App 传 probe 配置时，启动前把一份最小、无敏感
信息、带版本/过期时间的 flag JSON 放入应用 sandbox 的约定路径；App 的 debug-only 入口
读取并校验后执行，完成即删除。启动命令保持只有 UDID、`run` 与 bundle id。

Release 构建不得读取该文件；报告记录 flag 文件哈希和消费结果，不记录 token/凭据。
“命令没有报错”不证明参数已送达，必须由 App 写 probe acknowledgment 作为正向证据。

## 真机抓 log

```bash
# 推荐 — devicectl(iOS 17+,无需额外工具)
xcrun devicectl device console --device <UDID> 2>&1 | grep <关键词>

# 或 libimobiledevice(brew install libimobiledevice)
idevicesyslog | grep <关键词>
```

## 真机抓 crash 真值(idevicecrashreport)

启动数毫秒 crash / 启动闪退 / idevicesyslog 0 行 App 相关时,**抓 crash report 看 bug_type + 信号**:

```bash
# 拉真机 crash report 到本地(brew install libimobiledevice)
mkdir -p /tmp/crashreports
idevicecrashreport -e -u <UDID> /tmp/crashreports

# 列最新 .ips(JSON 格式)
ls -t /tmp/crashreports/<AppName>-*.ips 2>/dev/null | head -3

# Read 最新 .ips 看关键字段:
#   - bug_type:309(SIGTRAP / dyld 阶段)/ 109(EXC_BAD_ACCESS)/ 110(uncaught exception)/ 138(jetsam memory)
#   - exception type:EXC_BREAKPOINT / EXC_BAD_ACCESS / EXC_CRASH 等
#   - faultingThread frame:lldb_image_notifier(dyld)/ swift_error 等
#   - dyldErrorMsg(若有):dylib 名 + load fail 原因
```

**bug_type 速查表**:

| bug_type | 信号 | 典型根因 |
|---|---|---|
| **309** | EXC_BREAKPOINT / SIGTRAP | dyld load fail / 新版 Xcode `__preview.dylib` 注入(必加 `ENABLE_DEBUG_DYLIB=NO`)/ iOS 版本不兼容 dylib |
| 109 | SIGSEGV / EXC_BAD_ACCESS | 野指针 / Swift 强解包 nil / 释放后访问 |
| 110 | EXC_CRASH | uncaught exception / fatalError / preconditionFailure |
| 138 | jetsam | 启动初期内存过大 |
| 158 | sandbox | 文件权限 / 沙箱越界 / entitlement 缺 |

**何时跳过**:

- 启动 OK 跑一段时间后 crash → idevicesyslog 抓 stdout 优先(crash report 也可补)
- crash 信号已知(从代码 audit 即可看出 fatalError)→ 跳 idevicecrashreport 直接修

### crash 文本匹配必须验证非空语义

禁止用宽泛 `grep -iE 'error|signal|crash'` 直接生成 verdict。工具自己的字段名或空值也会
命中，例如 `fruitstrap_error_path=""` 只表示没有错误路径，却会被“包含 error”误报为崩溃。
优先解析结构化 crash report；只能扫文本时，模式必须约束有效值（如非空路径、明确
exception type/bug_type），并用空值行、调试器 teardown 与真实 crash 三组 fixture 验证。

## iOS 完工三步 + 真机自动 install(强制 hard rule)

iOS task md 完工三步走完(commit + merge develop + 删分支)后,**Dev 必自动跑 install + launch 到真机** — 用户拿到完工通知后真机直接可点击测试,不需再发指令。

### 完工三步 +1 install 完整流程

```bash
# 1-4 完工三步(标准)
git checkout -b dev/{user}/{slug} develop
git add ...
git -c user.name="<git-name>" -c user.email="<git-email>" commit -m "feat: ..."
git checkout develop
git -c user.name="<git-name>" -c user.email="<git-email>" merge dev/{user}/{slug} --no-ff -m "merge: ..."
git branch -d dev/{user}/{slug}

# 5. 真机自动 install + 持进程 launch(iOS task md 必含)
APP_PATH=$(find ~/Library/Developer/Xcode/DerivedData/<AppName>-*/Build/Products/Debug-iphoneos \
    -maxdepth 1 -name "<AppName>.app" -exec stat -f "%m %N" {} \; 2>/dev/null \
    | sort -rn | head -1 | cut -d' ' -f2-)
ios-deploy --id <UDID> --bundle "$APP_PATH" --no-wifi --justinstall
idevicedebug -u <UDID> run com.example.app.debug &
```

### 真机配置(协调端项目配置占位)

- **设备名**:`<设备名>`
- **UDID**:`<UDID>`
- **工具**:ios-deploy + idevicesyslog(brew install ios-deploy libimobiledevice)
- **协议**:usbmuxd(绕过新版 Xcode CoreDevice 兼容性 bug)

→ 协调端写 iOS task md 时,**完工三步段直接 hardcode UDID**,Dev 复制粘贴即跑。

### 何时跳过 install

- 仅 Spec 层纯逻辑改 / 单元测试 / 仅编译验证 → 不必 install(Spec 没 UI)
- xcodebuild build 失败 → 不进入 install 步(自然 abort);但**采集脚本仍须落 build_failed summary**,不得静默空手退出

### 判定线

iOS task md 完工三步段缺“安装 + 持进程 launch”第 5 步 = 不合格；launch 结果必须核对输出内容与截图渲染真值，不能只看 exit code 或 PID。

---

## ⚠️ Xcode beta 兼容性 — devicectl 失效时切 ios-deploy

**已知 bug**:某些 macOS + Xcode beta 组合上 `xcrun devicectl device install/launch` 报 "developer session not found",原因是 CoreDevice CLI 无法读 Xcode app 主程序的 developer session。

**绕过方案**:用 [ios-deploy](https://github.com/ios-control/ios-deploy) + [libimobiledevice](https://libimobiledevice.org/)(基于 Apple 底层 usbmuxd protocol,**不依赖 CoreDevice**):

```bash
brew install ios-deploy libimobiledevice

# 安装 .app + 持进程启动(替代 devicectl install + launch)
ios-deploy --id <UDID> --bundle "$APP_PATH" --no-wifi --justinstall
idevicedebug -u <UDID> run com.example.app.debug

# 抓 log(替代 devicectl console)
idevicesyslog -u <UDID> | grep <关键词>
```

**双方案对比**:

| 维度 | xcrun devicectl | ios-deploy |
|---|---|---|
| 协议层 | CoreDevice(Apple 高级框架) | usbmuxd(Apple 底层 USB protocol) |
| 依赖 | Xcode developer session(beta 易 broken)| device paired + 有效 provisioning profile |
| 稳定性 | 新工具,beta 版本 bug 多 | 社区维护多年,生产稳定 |
| 推荐 | macOS 稳定版 + Xcode 稳定版 | **Xcode beta 版本 fallback / CoreDevice 不工作时** |

**判定线**:`xcrun devicectl device install` 报 "developer session not found" / "no apple session" → **立即切 ios-deploy**,不要尝试修复 CoreDevice(Apple beta 内部问题,Dev 修不了)。

## Charles / Proxyman 真机抓包配置

1. **Mac**:启 Charles → Proxy → Proxy Settings → 端口 8888(默认)
2. **真机**:Settings → WiFi → 当前 WiFi → HTTP Proxy → Manual → Server: Mac IP / Port: 8888
3. **真机首次访问**:Safari 打开 `chls.pro/ssl`(Charles)或 `proxy.man/ssl`(Proxyman)→ 下载 SSL profile
4. **真机**:Settings → General → VPN & Device Management → Charles Proxy → Install
5. **真机**:Settings → General → About → Certificate Trust Settings → enable Charles / Proxyman 证书
6. **Charles**:Proxy → SSL Proxying Settings → Add 后端 host(`*.<domain>`)
7. App 内触发请求 → Charles → Sequence tab 看完整 HTTPS body

## 例外 — 仍可用 simulator

- **Spec 层纯逻辑改动**(不涉及 UI / 网络 / 系统能力)→ swift build / xcodebuild test simulator 快速迭代
- **单元测试**(`xcodebuild test`)→ simulator destination 仍 OK
- **仅编译验证**(`BUILD SUCCEEDED` 不 Run)→ simulator destination 仍 OK
- **Run + 实测必真机**

## 判定线

iOS task md 验证段缺真机 install + launch + log 抓 = 不合格(只 simulator 不够)。

---

## 受控真机数据夹具：难以手势构造历史状态时

当目标状态深埋在长列表、依赖特定历史记录或媒体文件，反复滚动和手势试探既慢又不可
复现。对明确授权的测试设备与 debug 包，可用 Android `run-as <bundle.id>` 导出/回写
应用私有数据库，并配套自造的非敏感媒体文件构造确定性场景。

边界：

1. 只允许用户明确授权的测试设备、debug 包和测试账号；生产设备、真实用户数据或无
   `run-as` 权限的路径一律禁止绕过。
2. 修改前备份数据库及 WAL/SHM，记录原文件哈希、目标表/主键、夹具内容与恢复命令；
   验收后恢复备份或清除测试记录。
3. 先停 App，再导出数据库到受控临时目录修改，回写后恢复文件属主与权限；不要在打开
   的 SQLite 上直接覆盖主文件。
4. 媒体夹具必须是自造或已授权素材，路径、扩展名和 metadata 要匹配生产读取契约。
5. 报告明确标记“人工构造夹具”，不得把它冒充线上自然数据；数据库快照与 UI 截图成对
   归档，并按 `ap-0210` 验证 UI 与持久层一致。

**判定线**：未记录授权、备份、夹具来源和恢复证据的私有数据回写，不得执行；只凭
手势碰运气或只留下截图的历史状态验收，也不得记为可复现通过。

---

# 接口 bug 诊断:BODY logging 必备

**铁律**:接口 bug(参数错 / 字段缺 / 响应空 / 超时)凭代码 grep + Read 不能定位根因,**必先开 BODY logging 抓真请求/响应**,再诊断。

**Why**:某次 submit 参数错根因诊断,Dev 凭代码 grep + Read 折腾 2 轮没找到 — 加 OkHttp BODY level 后 logcat 一次到位实证 body 字段 + response 错误码。iOS 同样 — Console / Charles / Proxyman 缺一,凭代码看不到真实响应字段。

## Android — OkHttp HttpLoggingInterceptor

```kotlin
// network/ApiClient.kt 或 NetworkModule.kt
HttpLoggingInterceptor().apply {
    level = if (BuildConfig.DEBUG) HttpLoggingInterceptor.Level.BODY
            else HttpLoggingInterceptor.Level.NONE  // release 不暴露 token / body
}
```

**抓 logcat**:
```bash
adb logcat -c
adb logcat | grep -E "OkHttp|<-- 200|<-- HTTP"  # 看完整 request body + response body
```

## iOS — Console / Proxyman / APIClient log

iOS 没有 OkHttp 这种现成 interceptor,三选一组合:

1. **Console**(轻量):`xcrun simctl spawn "<某 iPhone 型号>" log stream --predicate 'processImagePath CONTAINS "<AppName>"'` — 默认看不到 body,需 APIClient 自身 logger.d 配套
2. **Proxyman / Charles**(完整):Mac 端代理 + Simulator 配 HTTPS 抓包,看完整 request/response body — **接口 bug 诊断推荐路径**
3. **APIClient 自身 log**:`do { logger.d("request: \(body)"); let r = try await ...; logger.d("response: \(r)") } catch { logger.e("\(error)") }` — 不用 `try?` 吞错

## 双端通用规则

1. **接口 bug 诊断 task md**:必含"抓真响应实证"步骤,不只代码 grep + Read
2. **release 守门**:BODY 内容含 token / 用户敏感信息,release 必 `BuildConfig.DEBUG` 守门 / iOS `#if DEBUG`
3. **临时 logger.d 完工后清理**:debug 用临时 print/logger.d commit 前必删,只保留 BODY logging 作为长期 debug 工具(BODY level 守 DEBUG)
4. **接口响应字段实证 → DTO 决策**:抓到 BODY 后对照 API 文档 — 文档没列但响应有的字段 → DTO 直接补接(`@SerialName` / `CodingKeys` 映射),视为隐含字段

## 判定线

接口 bug 类 task md 缺"BODY logging 抓响应"实证步骤 = 不合格(Dev 会卡在凭代码诊断)。

---

## 关联

- 反模式集合(handoff 客观证据 / envelope 双键名 + try? 吞错全静默)
- `ap-0048`(install 选到旧 .app → 截图证据指向错版本,与本条"截图内容核对"互补)
- shared-rules `data-sources.md` §3 维同步铁律 接口维 — 接口实际响应优先于文档(本节提供抓响应工具)
