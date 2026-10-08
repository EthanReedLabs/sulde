---
doc_id: "ap-0036"
container: anti-patterns
platform: cross
summary: "macOS TCC 拦截 Claude Code agent 模拟器自动化输入"
---

# 0036 — macOS TCC 拦截 Claude Code agent 模拟器自动化输入

- **平台**:iOS Simulator（macOS 自动化）；Android Emulator 由 adb 驱动，不受 TCC 影响
- **复发次数**:0（首次发现 + 文档化为长期参考）
- **lint 状态**:N/A（系统层面限制，非代码反模式）

## ❌ 错误尝试 — 想用 agent 在 macOS 上自动化驱动 iOS Simulator 验证 UI

```bash
# 1. osascript 合成点击 → ❌
osascript -e 'tell app "System Events" to click at {835, 280}'
# Error -1719: osascript 不允许辅助访问

# 2. pyautogui → ❌（silent fail：无报错但 Simulator 无响应，截图前后像素一致）
python -c 'import pyautogui; pyautogui.click(835, 280)'

# 3. Swift CGEvent → ❌（同上 silent fail）
# 4. idb tap（Facebook iOS Device Bridge）→ ❌ 未安装
# 5. xcrun simctl ui → ❌（仅 appearance / contrast，无 tap/swipe API）
# 6. 项目无 XCUITest target / 无 deeplink → ❌
```

## 为什么错（根因）

macOS（15.x+）的 **TCC（Transparency, Consent, Control）** 子系统拦截所有合成输入路径：
- `CGEventPost` / `CGEvent.post(tap:)`（C/Swift 层）
- `osascript` 的 `click` / `keystroke`（System Events）
- `AppleEvent` 跨进程命令
- 第三方 GUI 自动化库（pyautogui / robotframework / Sikuli 底层都走 CGEventPost）

agent 默认沙盒身份（Terminal / Claude Code / osascript 子进程）**未在 隐私与安全性 → 辅助功能 中获得授权**，合成输入事件被静默丢弃。

## ✅ 正确处置（2 选 1）

**方案 A — XCUITest target（推荐，长期收益）**：

```swift
class ScenarioTests: XCTestCase {
    func testAuthOnTopOfCreateFlow() {
        let app = XCUIApplication()
        app.launch()
        app.tabBars.buttons["CREATE"].tap()
        app.cells["SomeEntry"].tap()
        app.buttons["Submit"].tap()
        XCTAssertTrue(app.otherElements["AuthDialog"].waitForExistence(timeout: 2))
    }
}
```

XCUITest 通过 Apple 官方 testRunner 进程内驱动，**完全绕开 TCC**。需在工程加 UITests target + accessibility identifiers + CI 编排。

**方案 B — 手工验证（短期 / 一次性）**：agent 提供详细手工步骤（simctl boot + install + launch + 截图基线），用户在 simulator 手工 tap + 截图归档。

**❌ 不推荐方案 C — TCC 授权**：给 Terminal 全局键鼠注入权限本质是权限 escalation；坐标 calibrate 脆弱（窗口移动 / 分辨率变化都失效）；长期维护成本 > XCUITest。

## lint 状态

- N/A（系统层面限制非代码反模式）

## 预防 / 决策原则

- agent 验证 iOS UI 行为时，**默认走"静态分析 + 手工验证"**，不期望自动点击
- 长期防回归 → 投资 XCUITest target，纳入 CI
- agent handoff 描述 UI 验证 = 必含"手工步骤"或"XCUITest 用例 ID"，**不要承诺自动化**

典型适用：iOS Simulator 任何 tap/swipe/type 自动化 / macOS GUI 应用自动化 / 跨应用键鼠合成事件 → 直接走方案 A 或 B，不再尝试 osascript / pyautogui / CGEvent。
