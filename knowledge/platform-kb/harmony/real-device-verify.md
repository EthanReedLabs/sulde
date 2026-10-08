---
doc_id: "platform-kb/harmony/real-device-verify"
container: platform-kb
platform: harmonyos
summary: "真机 verify(v1.1)"
---

# 真机 verify(v1.1)

## A. 自动序列(Dev 每完工必跑)

```bash
source <project>/scripts/setup-deveco-env.sh
cd <project>/<harmony-module>
hvigorw assembleHap --mode module -p product=default --no-daemon
hdc list targets
hdc install -r entry/build/default/outputs/default/entry-default-signed.hap
hdc shell aa start -a EntryAbility -b com.example.app
hdc shell hilog | grep -E "<APP_TAG>|<PAGE_TAG>"
```

**禁** punt 用户/协调端跑:build / install / 真机验证由 Dev 自己完成(内部规则)。

## B. hilog filter / 排查

| filter | 用途 |
|---|---|
| `\| grep <APP_TAG>` | 业务日志 |
| `\| grep -iE "<APP_TAG>.*(crash\|fatal\|error\|exception)"` | 找真 crash |
| `\| grep -iE "<APP_TAG>.*(GET\|POST)"` | 看 endpoint 调用 |
| `\| grep "<某页> appear"` | 启动到达目标首页 |

**假阳过滤**:`CRASH: init done`(CrashService init log)/ `AceTheme/AceResource` system warns 都非真 crash。

## C. dark + light 双模式 verify(强制)

切系统主题:
- 设置 → 显示和亮度 → 深色 / 浅色
- 切后冷启 app 一次(若主题切换运行时不响应)

各 verify:
- 顶部背景图 dark 暗色调 / light 亮色
- color tokens 自动切(text_primary / bg_primary / brand_primary)
- asset 自动走 dark/media 同名覆盖

## D. 截图 / 视觉对比 Flutter

```bash
hdc shell snapshot_display -f /data/local/tmp/screen.jpeg
hdc file recv /data/local/tmp/screen.jpeg .ai-workspace/screenshots/
```

handoff §5 视觉对比表(Pre-merge gate):

| # | 元素 | Flutter (dark/light) | Harmony (dark/light) | 一致? |
|---|---|---|---|---|
| ... | ... | ... | ... | ✅ / ❌ |

**❌ ≥ 2 → 协调端 REJECT merge**;❌ ≤ 1 → merge OK + polish 单独派。

## E. Verify scope split

| 由 Dev 跑 | 由用户跑 |
|---|---|
| build / install / aa start / hilog 0 crash | 多 Tap UI 操作流(eg 弹窗 tap 触发) |
| cold-start 单截图全 element 覆盖 | 网络断网 EmptyDataPage 触发 |
| 单 widget visual render OK | 跨页跳转回归 |

Dev session 真机 only 单一帧 / 不便 multi-step user flow → 这些 user 跑。

## F-pre. 视觉对照 Flutter 真值(短期 + 长期组合)

**短期**:user dump Flutter 真机各 state 截图 → `docs-hub/flutter-reference/<tab>/<state>.jpeg`,协调端起 task md 时 ref;Dev handoff §5 视觉对比表 fill `Flutter ref jpeg | Harmony 真机 jpeg | 差异 | ✅/❌`。

详 `docs-hub/flutter-reference/<tab>/README.md` 截图 state 清单。

**长期**:HarmonyOS `@ohos/hypium` uitest + Driver.takeScreenshot + Pixel diff util(容差 5%),跑 `hvigorw test --product ohosTest` 自动跑 → fail 时 commit failed screenshot 到 handoff。setup 一次即长期 ROI。

## F. 真机问题归类

| 现象 | 看 kb |
|---|---|
| 视觉异常(尺寸 / 位置 / 颜色) | `arkui-components.md` + `arkui-incompatibility.md` |
| 视觉不显 / 灰白屏 | `arkui-incompatibility.md`(asset bg + Dashed 不可共存等) |
| dark mode 偏 | `resources-system.md`(dark/media 是否迁) |
| 编译 ERROR | `arkts-language.md` |
| 跳转不工作 | `routing-navigation.md` |
| 字段空 / null | `network-api.md` JsonHelper |
| 状态不更新 | `state-management.md` |

## G. uitest 限制(v1.1,spike 实证)

### G.1 ⚠️ `uitest uiInput click <x> <y>` 对 Navigation/NavDestination 内 Button 不可靠

**症状**:Navigation+NavDestination 渲染的 Button,uitest click 真机不触发 onClick。

**根因推测**:Navigation 组件事件路由 bypass uitest 触摸注入路径(可能 vsync / focus 状态不一致)。

**Workaround**:
- ✅ **首选**:`setTimeout` 自动触发 state(spike repro 用,模拟用户 tap)
- ✅ **替代**:真人手动操作(协调端 2 机驱动时常用)
- ⚠️ **退化**:`uitest uiInput keyEvent KEYCODE_ENTER` 模拟键盘事件(若 widget 支持 focus + Enter)
- ❌ **不可靠**:`hdc shell input tap <x> <y>`(同样 bypass)

**实证**:spike 中用 setTimeout 自动 cascade 4 层 dialog(uitest click 试过不响应,改 timer 后通)。

### G.2 spike worktree 简化 EntryAbility 模式

**症状**:spike worktree 沿用主 EntryAbility(含三方 SDK/AppBootstrap)→ `GetRequestedModuleMayThrowError request module is hole` crash(module dep graph 跨 worktree 不一致)。

**Workaround**(spike worktree 限定):
```ts
// EntryAbility.ets:spike 隔离最简版(~37 行,完工随 branch 删)
import { UIAbility, Want } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';

export default class EntryAbility extends UIAbility {
  onCreate() { hilog.info(0x0001, 'SPIKE', 'EntryAbility onCreate'); }
  onWindowStageCreate(stage: window.WindowStage) {
    stage.loadContent('pages/spike/SpikeXxxNavPage', (err) => {
      if (err.code) return;
      hilog.info(0x0001, 'SPIKE', 'NavPage loaded');
    });
  }
}
```

**不动 main worktree EntryAbility**(spike branch 完工删 worktree 即可,develop 不受影响)。
