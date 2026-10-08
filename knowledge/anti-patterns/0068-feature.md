---
doc_id: "ap-0068"
container: anti-patterns
platform: none
summary: "0068 Feature 模块重复造脚手架轮子"
---

# 0068 Feature 模块重复造脚手架轮子

- **平台**:双端(同源)
- **复发次数**:≥ 5

## ❌ 错误

多个 feature 模块各自手画 title bar(返回按钮 + 标题),不复用 core-ui 的共享 `AppTopBar`。

Android:

```xml
<!-- 每个 feature 的 layout 都自己拼 title bar -->
<LinearLayout android:orientation="horizontal" android:layout_height="48dp">
    <ImageView android:src="@drawable/ic_arrow_back"
        android:onClick="onBackClick"/>          <!-- ❌ 自绘返回 -->
    <TextView android:textSize="18sp"
        android:textStyle="bold"/>                <!-- ❌ 自绘标题(每页字号/字重不一致) -->
</LinearLayout>
```

iOS 同源:

```swift
// 每个 Feature/View 自拼 HStack 当 title bar
HStack {
    Button(action: { dismiss() }) { Image(systemName: "chevron.left") }
    Spacer()
    Text(title).font(.system(size: 18, weight: .semibold))
    Spacer()
}
.padding(.horizontal, 16)
.frame(height: 48)
```

同源衍生:每页自做 toast 浮层 / 自写 confirm dialog / 自绘 bottom sheet。

## 为什么错

- N 个 Feature 各自实现一份 title bar = N 份不一致视觉(字号 / spacing / icon 大小 / 返回行为);
- 设计稿改一次 title bar → N 个模块改 N 处;
- 系统级安全区(状态栏 inset / 刘海 / 异形屏)在 N 个自绘 title bar 中各踩各的坑;
- scaffold(AppTopBar / Toast / ConfirmDialog)价值被绕过,出 bug 无法集中修。

## ✅ 正确

```xml
<!-- Android: 复用 core-ui 的 AppTopBar -->
<AppTopBar
    android:layout_width="match_parent"
    android:layout_height="wrap_content"
    app:appTitle="@string/settings"
    app:appShowBack="true"/>
```

```swift
// iOS: 复用 CoreUI 的 AppTopBar
AppTopBar(title: title, onBack: { dismiss() })
```

### ALLOWLIST 清零原则(scaffold lint 强化)

为兼容旧 feature 自绘 title bar 而在 lint 里引入的 `ALLOWLIST` 豁免段**是技术债**,会让新 feature 学着也加进 allowlist 绕过规则。

**正确**:ALLOWLIST 必须最终清零。每个 ALLOWLIST 条目是显式标记的"待迁移到 AppTopBar"任务,迁移完毕后立即从 lint 脚本删除。allowlist 机制本身在所有条目清零后**也要移除**(避免再次被滥用)。

## lint 状态

- Android:✅ lint 规则(grep feature 内含自绘 title bar pattern 即 fail;ALLOWLIST 已清零 + 机制移除);
- iOS:⏳ TODO — 检测 Feature 内 `private var navRow/titleBar` 含 chevron 但无 AppTopBar 调用。

## 预防

Feature 模块写任何"通用 UI 元素"前**第一反应是查 core-ui / CoreUI scaffold**:
1. 先 grep scaffold 目录看是否已有;
2. 没有 → 派 scaffold 任务,由架构层抽到 core-ui 后 Feature 调用;
3. **永远不在 Feature 模块自做基础组件的复制版**。

## 关联

- 系统级安全区 / 标题贴状态栏(自绘 title bar 必踩同源)
- MVI 基类不继承统一 BaseActivity(同源 — 重复造基类轮子)
