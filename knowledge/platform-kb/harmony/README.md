---
doc_id: "platform-kb/harmony/README"
container: platform-kb
platform: harmonyos
summary: "写 `.ets` / 排 ArkUI 视觉异常 / 转译 Flutter→ArkUI 前,**先 Read 对应分类…"
---

# HarmonyOS / ArkUI / ArkTS 知识库 — 分类索引

> 写 `.ets` / 排 ArkUI 视觉异常 / 转译 Flutter→ArkUI 前,**先 Read 对应分类 file**,找已知 rule + workaround;未命中 → 实施 + 回补。
> 脱敏自实战沉淀(HarmonyOS SDK 5.x–6.x / API 12–23 区间),项目无关。单文件累积过长 → split 子文件(如 `arkui-components-image.md` / `-layout.md`)。

## 分类索引(lookup 入口)

| 类 | file | 何时 Read |
|---|---|---|
| **1. ArkTS 语言陷阱** | `arkts-language.md` | 写 .ets 前 / 编译 ERROR / `@Prop` 撞名 / `any` 报错 / `instanceof` narrowing 失败 |
| **2. ArkUI 组件 API** | `arkui-components.md` | Stack/Row/Column/Grid/Scroll/List/Image/Text/Alignment enum / 组件 prop 行为 |
| **3. ArkUI 不可共存 / workaround** | `arkui-incompatibility.md` | 视觉异常 / 某 modifier 不渲染 / 组合不可共存 + 已知 workaround |
| **4. 资源 / 主题** | `resources-system.md` | asset 迁移 / dark mode / color token / `$r()` / SDK 资源命名 |
| **5. 路由 / 导航 / 浮层** | `routing-navigation.md` + `routing-navigation-overlay-frames.md` | NavPathStack / Router / NavDestination / Dialog / 浮层返回 frame 归属 |
| **6. 状态管理** | `state-management.md` | `@State` / `@Link` / `@Prop` / `@StorageProp` / AppStorage / EventHub |
| **7. 网络 / API** | `network-api.md` | HttpClient 实例 / 业务码 unwrap / JSON helper / Result narrowing |
| **8. 构建 / 工具链** | `build-toolchain.md` | DevEco 环境 / hvigorw / hdc / SDK 版本 / 签名 scheme |
| **9. 真机 verify** | `real-device-verify.md` | hilog filter / 自动 install / 截图 / dark+light 双模式 |
| **10. Flutter → ArkUI 翻译** | `translate-rules.md` | UI 还原 / 逐行 transpile Flutter widget → ArkUI ets |
| **11. ArkWeb / Web 组件** | `arkweb.md` | Web 渲染空白 / 加载 HTML 字符串 / Web 内注入主题 CSS |
| **12. 滚动页壳 / 固定标题栏** | `arkui-layout-scroll-shell.md` | Tab 首页 / AppBar 渐显 / parallax / overscroll / 右侧溢出 |

## Lookup protocol(3 步)

1. **看类**:问题属哪类?(看上表"何时 Read"列)
2. **Read kb file**:找已知 rule + workaround,逐条对照
3. **未命中** → 实施 + 记录,回补对应 file(实战反哺)

> 反模式单点条目见 [`../../anti-patterns/INDEX.md`](../../anti-patterns/INDEX.md) HarmonyOS 段;深复盘见 [`../../tech-docs/案例研究/06-HarmonyOS-ArkUI工程/`](../../tech-docs/案例研究/06-HarmonyOS-ArkUI工程/)。
