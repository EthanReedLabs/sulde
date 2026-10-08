---
doc_id: "ap-0115"
container: anti-patterns
platform: android
summary: "EncryptedSharedPreferences 无解密兜底启动闪退"
---

# 0115 — EncryptedSharedPreferences 无解密兜底启动闪退

- **平台**:Android(iOS Keychain 机制不同,跨端排查 backlog)
- **复发次数**:0(首次沉淀)

## ❌ 错误

Android `androidx.security:security-crypto` `EncryptedSharedPreferences.create()` 无 try/catch 直调,当 AndroidKeyStore master key 与 Tink keyset 错配时抛 `AEADBadTagException` → 进程启动期同步路径未兜底 → 启动即 FATAL → 用户设备进入"永久启动闪退"态需卸载重装才恢复。

```kotlin
class SecureStorage(context: Context) {
    private val prefs: SharedPreferences = EncryptedSharedPreferences.create(
        context,
        FILE_NAME,
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
    )   // ← 抛 AEADBadTagException 时无 catch,Application.onCreate 链路全崩
}
```

**完整 crash 链**:`Application.onCreate → SessionService → SessionStore.loadInitialSession → getAccessToken → SecureStorage.getString → EncryptedSharedPreferences.create` 抛 `AEADBadTagException`(底层 `KeyStoreException: Signature/MAC verification failed`)。

## 为什么错

- **AndroidKeyStore master key 与 Tink keyset 错配** 是已知 bug,真实触发面:系统更新后 keystore 轮换 / 换机恢复备份 / 锁屏凭据或生物识别重置 / 部分 ROM 卸载重装。
- **`androidx.security:security-crypto` 已 deprecated**(2024 起),bug 官方不修。
- **进程启动期同步读 token** 无兜底 → 错配直接闪退,用户无自愈路径(必须卸载重装,丢未同步数据)。

## ✅ 正确

```kotlin
class SecureStorage(context: Context) {
    private val prefs: SharedPreferences = try {
        createEncryptedPrefs(context)
    } catch (e: GeneralSecurityException) {
        rebuildPrefs(context)
    } catch (e: IOException) {
        rebuildPrefs(context)
    }

    private fun rebuildPrefs(context: Context): SharedPreferences {
        // 1. 删损坏 prefs 文件
        context.deleteSharedPreferences(FILE_NAME)
        // 2. 删 master key alias(防新建 prefs 仍命中老 keyset)
        try {
            val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            keyStore.deleteEntry(MasterKey.DEFAULT_MASTER_KEY_ALIAS)
        } catch (_: Exception) { /* best-effort */ }
        // 3. 重建空 prefs
        return createEncryptedPrefs(context)
    }
}
```

**副作用**:错配时登录态丢失 = 用户被登出(读 null token → 走未登录流程,无异常),**远好于启动闪退**。

## 判定线

- `EncryptedSharedPreferences.create()` 调用未包 try/catch `GeneralSecurityException` / `IOException` → ❌。
- catch 后未 `deleteSharedPreferences` + 未删 master key alias → ❌(只重建 prefs 不删 alias 会复发,新 prefs 仍命中老损坏 keyset)。
- 进程启动期同步路径调 EncryptedSharedPreferences 未兜底 → ❌。

## lint 状态

- ✅ Android 已落地:grep `.kt` 含 `EncryptedSharedPreferences.create` 但同文件无 `deleteSharedPreferences` → 报违规(自愈兜底缺失)。

## ⚠️ iOS 跨端注脚

iOS token 存 Keychain,机制不同(系统管理 vs Tink keyset),**但未必无同类风险**:换机 / iCloud Keychain 还原 / `kSecAttrAccessibleAfterFirstUnlock` 错配等场景可能有未兜底崩溃路径。已派 backlog audit(对照 Android 修法寻找 iOS 等价兜底点)。触发后单独沉淀(不并入本款,机制不同)。

## How to apply

- Android 任何调 `EncryptedSharedPreferences.create()` 处必包 try/catch + 自愈兜底。
- 协调端 task md 涉及加密本地存储时,代码示例必含完整 catch + `deleteSharedPreferences` + 删 master key alias 三步自愈链。
- `/code-review` checklist 加:启动期同步路径调 EncryptedSharedPreferences 是否有兜底?
- 长期:`security-crypto` 已 deprecated,规划迁移 DataStore + 自管 Tink。

## 关联

- Dev 自发修边界(本款命中"user 口头授权基础设施层 self-fix")。
- self-fix-boundary 敏感清单「scaffold / 基础设施层」+「登录会话链」。
