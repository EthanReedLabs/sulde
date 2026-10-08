---
doc_id: "ap-0102"
container: anti-patterns
platform: cross
summary: "0102 WebView evaluateJavascript 注入 localStorage 的 3 个时序坑"
---

# 0102 WebView evaluateJavascript 注入 localStorage 的 3 个时序坑

- **平台**:Android(确认)/ iOS WKWebView(同源待防)
- **复发次数**:1

## ❌ 错误(Android)

```kotlin
override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
    if (!injectionDone) {
        injectToken(view)                                       // 坑 1
        injectionDone = true
        view?.reload()                                          // 坑 2
    }
}

private fun injectToken(webView: WebView?) {
    val session = sessionService.currentSession.value           // 坑 3
    val storageValue = buildUserStorageValue(session) ?: return
    val escaped = storageValue.replace("\\", "\\\\").replace("'", "\\'")
    webView?.evaluateJavascript("localStorage.setItem('app-user', '$escaped');", null)
}
```

## 为什么错(3 个独立 sub-root)

- **坑 1:注入时机错**。`onPageStarted` 时 WebView 新页 JS 上下文未完整建立,`evaluateJavascript` 可能写到错误 origin 或被丢弃。**必须在 `onPageFinished` 注入**。
- **坑 2:reload race condition**。`evaluateJavascript(..., null)` 是 fire-and-forget 异步,排队到 JS 线程;紧跟 `view.reload()` 立即销毁当前 JS 上下文,排队中的 setItem 在执行前被取消。logcat 实证 `读出 = null`(setItem 从未生效)。**必须把 reload 写进 JS 字符串内同步执行** 或 等 callback 触发后再 reload。
- **坑 3:Session.user 可能 null**。`accessToken` 已写入但 `setUserInfo` 未触发(登录流程或冷起 session 恢复时 race),`session.user?.userId ?: return null` 直接早返回,整个注入逻辑静默跳过。**必须主动拉真值(`getProfile()`),不依赖 SessionService.user**。

## ✅ 正确(Android)

```kotlin
override fun onPageFinished(view: WebView?, url: String?) {
    if (!injectionDone) {
        injectionDone = true
        injectTokenThenReload(view)
    } else {
        progress.visibility = View.GONE
    }
}

private fun injectTokenThenReload(webView: WebView?) {
    val token = sessionService.currentSession.value.accessToken ?: run {
        progress.visibility = View.GONE; return
    }
    lifecycleScope.launch {
        val profile = userService.getProfile().getOrNull() ?: run {
            progress.visibility = View.GONE; return@launch
        }
        val storageValue = buildUserStorageValue(accessToken = token, profile = profile)
        val escaped = storageValue.replace("\\", "\\\\").replace("'", "\\'")
        // setItem + reload 同一 JS 帧内同步执行,杜绝 callback race
        val script = "localStorage.setItem('app-user', '$escaped'); window.location.reload();"
        webView?.evaluateJavascript(script, null)
    }
}
```

## ✅ 正确(iOS WKWebView)

### 方案 A — `WKUserContentController` 在 `documentStart` 阶段注入(推荐,比 reload 兜底更优)

```swift
let userScript = WKUserScript(
    source: "localStorage.setItem('app-user', '\(escapedJson)');",
    injectionTime: .atDocumentStart,
    forMainFrameOnly: true
)
let config = WKWebViewConfiguration()
config.userContentController.addUserScript(userScript)
```

### 方案 B — 同 Android,`didFinish` 内 JS 同步 `setItem + location.reload()`

```swift
func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
    guard !injectionDone else { return }
    injectionDone = true
    Task {
        guard let token = sessionStore.accessToken,
              let profile = try? await userService.getProfile() else { return }
        let json = buildUserStorageValue(token: token, profile: profile)
        let escaped = escapeForJSSingleQuotes(json)
        let script = "localStorage.setItem('app-user', '\(escaped)'); window.location.reload();"
        webView.evaluateJavaScript(script)
    }
}
```

## lint 状态

- ❌ 无法静态检查(运行时时序 / 异步 race 语义,静态 grep 误报率高)→ 人工 review checklist。

## 人工 review checklist(接 WebView 注入 task 必查)

1. 注入是否在 `onPageFinished`(Android)/ `didFinish`(iOS)?**不能在 onPageStarted / didStartProvisional**(JS 上下文未完整)。
2. `evaluateJavascript` 异步性是否被忽略?检查紧跟 `reload()` 是否丢失 setItem。
   - Android 正确姿势:JS 字符串内同步 `setItem + location.reload()`,或 callback 内 reload。
   - iOS 推荐:`WKUserScript` + `.atDocumentStart` 绕过 reload 兜底。
3. 注入数据来源:是否假设 `Session.user` 已就绪?登录态恢复 / 冷起场景 `user` 可能 null 但 `accessToken` 有 → 必须主动 `getProfile()` 拉真值。

## 关联

- 文档真值 JSON 必完整 quote,不裁字段(本案踩坑触发)。
- grep 命中 ≠ runtime 真值(本案靠 logcat 实证 `读出 = null` 才定位坑 2)。
