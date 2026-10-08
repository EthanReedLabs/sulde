---
doc_id: "ap-0130"
container: anti-patterns
platform: none
summary: "0130 协调端跨端镜像 task md 写 L10n 文案 diff 前未 grep 全部引用点 → 一 key 多…"
---

# 0130 协调端跨端镜像 task md 写 L10n 文案 diff 前未 grep 全部引用点 → 一 key 多用直改污染

- **平台**:协调端
- **复发次数**:0

## ❌ 错误

协调端起跨端镜像 task md 时,baseline grep 单一引用点就写"文案 X 改 Y"方案:

```diff
-"profile.tasks.rename" = "Rename";
+"profile.tasks.rename" = "Edit Title";
```

实际该 L10n key **同时用于多个 UI 场景**:菜单按钮标签 + 弹窗标题。直改会让菜单按钮也变 "Edit Title" — 与另一端发散(另一端已拆 key:菜单按钮一个 key,弹窗标题另一个 key)。

## 为什么错

- 一 key 多用直改导致其他场景文案被污染或双端发散。
- 跟踪表看似闭环实际 regression。

## ✅ 正确

改值前**先 grep 全部引用点 + 对照另一端是否已拆 key**:

```bash
# 全面命中数
grep -rn "profile\.tasks\.rename" Sources/CoreUI/Resources/ Sources/Feature*/
# 命中 ≥2 处 → ⚠️ 标"该 key 多用,Stage 1 自审决定改值 vs 拆 key"
# 命中 = 1 → ✅ 直改安全

# 对照另一端是否已拆 key
grep -rn "task_action_rename\|task_rename_dialog_title" ../android-端/.../strings.xml
```

修法 = 拆 key:

```diff
"profile.tasks.rename" = "Rename";             // 保留菜单按钮
+"profile.tasks.rename_dialog_title" = "Edit Title";   // 新增弹窗标题 key
```

适用扩展:L10n key 改值 ✅ / Drawable / Asset 资源名改值 ✅(可能多 View 引用)/ Color token 改值 ✅ / 单 key 仅 1 处 ❌ / 新增 key ❌。

## lint 状态

❓ task md 写作期 lint(非编译/运行期)— 协调端写完 task md 后跑 verify:diff 含 L10n key 改值 + 该 key 源码 grep 命中 ≥2 处 → 警告"L10n key 多用,直改前 verify 拆 key"。

## 关联

- adapter wrap ≠ 真链路(同源:凭单一证据反推)
- 协调端 task md baseline 缺(本反模式是其子模式:baseline grep 单一引用点 ≠ 全面 audit)
