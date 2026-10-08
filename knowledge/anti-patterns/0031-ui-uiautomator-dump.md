---
doc_id: "ap-0031"
container: anti-patterns
platform: android
summary: "UI 对齐任务误用 uiautomator dump 代替多模态看图"
related: [ap-0216]
---

# 0031 — UI 对齐任务误用 uiautomator dump 代替多模态看图

- **平台**:Android（视觉对齐场景）
- **lint 状态**:bash 命令模式，无法静态 lint

## ❌ 错误

把"UI 视觉对齐"（多模态看图任务）等同为"UI 自动化测试"（抓坐标 + 模拟点击）：

```bash
# 自动化 dump + grep bounds 抓按钮坐标，再模拟点击到目标页后截图
adb shell uiautomator dump /sdcard/d.xml
adb pull /sdcard/d.xml /tmp/d.xml
grep -oE 'text="Select"[^<]{0,1000}bounds="\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]"' /tmp/d.xml
adb shell input tap 540 2247
adb shell screencap -p /sdcard/s.png
adb pull /sdcard/s.png /tmp/s.png
# ……然后才 Read /tmp/s.png 做视觉对比
```

## 为什么错

- `uiautomator dump` + `grep bounds` 的本质是"用机器方式找 UI 元素位置"，目的是为自动化点击服务
- 原生多模态，`Read PNG` 直接看得见 UI 内容，不需要先解析 UI 树
- 用户主动截图 / 已手动到目标页时 = 明确不要自动化路径
- 走 dump + grep 路径是效率反优化：多 3-4 次 adb 往返 + XML parse + grep 定位

## ✅ 正确（用户已到目标页，直接截图 + 多模态 Read）

```bash
adb exec-out screencap -p > /tmp/runtime.png
# Read /tmp/runtime.png（多模态直接看图）
# 对照 Read pen-truth/{pageId}.png + .md
```

两种任务区分：

| 任务类型 | 正确路径 |
|---|---|
| UI 视觉对齐（本条目）| adb screencap + Read 多模态，无需 dump XML / 抓 bounds |
| 功能流程测试 | adb input tap（按业务流程模拟用户点击，不是为抓坐标）|
| 自动化回归（长期）| UI Automator / Espresso 测试框架（代码化，不在 /ui-impl 范围）|

## lint 状态

- ❌ 无法静态 lint（bash 命令顺序模式）
- /ui-impl skill 验证段加硬约束："UI 视觉对齐用 `adb screencap` + `Read`，禁止 `uiautomator dump` + `grep bounds` 抓坐标"

## 关联

- 两端 `/ui-impl` skill 验证阶段
