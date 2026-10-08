---
doc_id: "ap-0178"
container: anti-patterns
platform: cross
summary: "0178 流式诊断日志缺少编译闸与字段脱敏双闸"
---

# 0178 流式诊断日志缺少编译闸与字段脱敏双闸

- **平台**:跨端
- **复发次数**:0

## ❌ 错误

流式诊断日志把凭证、URL、标识符或完整载荷拼成明文，再以 public 文本写入系统日志或本地文件：

```swift
let line = "connect url=\(url) token=\(token) payload=\(payload)"
logger.debug("\(line, privacy: .public)")
appendToFile(line)
```

只依赖 `os.Logger` privacy 或只使用 `#if DEBUG` 都不完整。

## 为什么错

`os.Logger` privacy 不覆盖自行写入的明文文件；`#if DEBUG` 也不能阻止调试包、日志导出或共享设备暴露敏感字段。编译闸控制诊断路径是否存在，字段脱敏控制路径存在时暴露多少，两者防护的泄漏渠道不同。

## ✅ 正确

诊断入口先受编译闸控制，所有输出目的地再统一使用字段级脱敏结果：

```swift
#if DEBUG
let safeCredential = redactCredential(token)
let line = "connect credential=\(safeCredential)"
logger.debug("\(line, privacy: .private(mask: .hash))")
appendToFile(line)
#endif
```

优先只记录长度、是否存在、域名或不可逆摘要；禁止记录完整凭证和载荷。本地镜像需定义访问权限、容量上限与清理周期。

## lint 状态

- ⏳ 可扫描日志插值中的凭证、邮箱、密码、完整载荷等高风险字段，并检查诊断入口是否受 `#if DEBUG` 控制。
- 人工 review：确认 `os.Logger` 与文件、控制台、导出包等每个 sink 都消费同一脱敏结果。
- 关联：用户可见输出的本地化治理与诊断输出的隐私治理都应在输出边界设闸。
