---
doc_id: "ap-0050"
container: anti-patterns
platform: cross
summary: "0050 后端 envelope 双键名(`msg` vs `message`) + 严格 decode + `try?"
---

# 0050 后端 envelope 双键名(`msg` vs `message`) + 严格 decode + `try?` 三连 → 全模块静默

- **平台**:iOS(确认) / Android(同类风险)
- **复发次数**:1

## ❌ 错误 — 症状

某接口 console log 显示 nw_connection ready(实际命中后端),`curl` 直打后端返数据,**App 业务层始终空**。

## 为什么错(根因)

- 后端 envelope:`{"code": 0, "msg": "", "data": {...}}`(用 `msg`)
- iOS `APIResponse<T>`:`{ code: Int, message: String, data: T? }`(`message` 非 Optional 严格 decode)
- `JSONDecoder.decode(APIResponse<T>.self, ...)` 抛 `keyNotFound("message")`
- 业务层 `try? await client.method()` **吞掉 throw → 空数组 → UI 空状态**(完全静默)

三事实合体:**键名不匹配 + 严格 decode + try? 吞错 → 全链路无任何错误信号**。

## ✅ 正确 — 修法

1. **envelope decode 容错多键名**:
   ```swift
   public init(from decoder: Decoder) throws {
       let c = try decoder.container(keyedBy: CodingKeys.self)
       self.code = try c.decode(Int.self, forKey: .code)
       // message 优先 message,回退 msg,再回退 ""
       self.message = (try? c.decode(String.self, forKey: .message))
                   ?? (try? c.decodeIfPresent(String.self, forKey: .msg))
                   ?? ""
       self.data = try c.decodeIfPresent(T.self, forKey: .data)
   }
   ```
2. **业务层 / Adapter `try?` 吞错前必 log 一次**(便于诊断):
   ```swift
   do { return try await client.method() }
   catch { logger.error("decode failed: \(error)"); return [] }
   ```
3. **协调端 review** Spec 层 envelope 时:
   - 必须查后端文档 / curl 真实响应,**确认字段名**
   - decode 不要无脑 `decode(String.self,)`,可用 `decodeIfPresent` + 默认值
   - **Adapter 层禁止裸 `try?`**,至少 log

## 判定线

iOS `try?` 在 Adapter / Feature 业务层出现时 grep:

```bash
grep -rn "try? await\s*\w\+Client\." Sources/Adapter*/ Sources/Feature*/  # 应有 log 配套
```

## Android 同类风险

- `ApiResponse.kt` `message: String? = null` — Optional + 默认 null,**Moshi 自动兼容字段缺失**(JSON 无 `message` 时不抛异常,直接 null)
- 但**实际后端字段是 `msg`,`ApiResponse.message` 始终读到 null** → 错误信息丢失,功能性 bug 但不致命
- 修法:`ApiResponse.message` 双键名兼容(Moshi 不直接支持多键名,需自定义 JsonAdapter)

## lint 状态

- iOS:⏳ TODO(grep `try? await.*Client\.` 后必有 log 配套)
- Android:⏳ TODO(自定义 JsonAdapter 双键名兼容)

## 关联

- 客观证据规则 — 验收 handoff 时若声明"接口接通"必须 grep `staging-api` 真实命中而非 nw_connection ready
- 协调端凭印象 — Spec 端 envelope 字段名必查后端文档而非旧版抄,本条是其隐性变种
