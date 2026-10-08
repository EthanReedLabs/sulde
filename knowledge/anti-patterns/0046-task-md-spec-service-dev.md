---
doc_id: "ap-0046"
container: anti-patterns
platform: none
summary: "0046 协调端写双端 task md 未硬约束 Spec / Service 组织一致 → 双端 Dev 各自合理选…"
---

# 0046 协调端写双端 task md 未硬约束 Spec / Service 组织一致 → 双端 Dev 各自合理选择 → 后续接口接入差异

- **平台**:协调端(双端 task md 写作类)
- **复发次数**:1

## ❌ 错误现象

某接口模块双端实施差异:

| 端 | Spec 层组织 | 数据模型 | 协议 method |
|---|---|---|---|
| iOS | 模型放进 `Sources/Spec/<X>Models.swift`,**没建独立 Client** | 命名 A 套 | ❌ 无 |
| Android | **新建独立 `core-spec/.../<X>Service.kt`** | 命名 B 套 | ✅ 若干 method |

**全量 RealAdapter 接入时差异暴露**:
- Android `Real<X>Adapter` 直接接入 ✅
- iOS 没 Client struct → 无可接入对象 → 该模块 0 method 留微 task 补

**为什么错(协调端 task md 设计漏洞)**:
协调端 task md 让 Dev 自己 grep 现状 + 自由判断 gap 处理方式,**没显式硬约束双端 Spec 层组织一致**:
- iOS 看 Spec 已有周边,选"扩展放 Models.swift"
- Android 看 core-spec 没现成 Service,选"新建独立 Service"

**双方都不算错**,都是合理设计选择。但**协调端没硬约束 = 双端隐性分化 = 后续接入差异**(handoff 看不出 Spec 层差异,写 RealAdapter 才暴露)。

## 为什么错(根因)

- 双端独立 Dev 各自合理选择 = 隐性分化(handoff 看不出)
- 全量接入时差异暴露 → 微 task 修补的代价
- 协调端是双端"对齐者",**任由 Dev 各自判断 = 协调端失职**
- 凭印象类反模式是协调端写文档凭印象;本条是协调端**没显式约束的隐性凭印象**(让 Dev 自由判断 = 协调端没规划)

## ✅ 正确 — 协调端写双端 task md 涉及 Spec 层组织时,必显式列双端清单 + 同名同签名硬约束

### a. 双端 Spec 层组织清单(写双端 task md 前协调端先列)

```markdown
| 模块 | iOS 文件 / 类名 | Android 文件 / 类名 | method 签名 |
|---|---|---|---|
| 模块 A | Sources/Spec/AClient.swift | core-spec/.../AService.kt | methodA() / methodB(id) |
| 模块 B | Sources/Spec/BClient.swift | core-spec/.../BService.kt | listFeed / markAsRead / unreadCount |
```

### b. 双端 task md 显式引用同一份清单

iOS / Android task md 都内嵌同一组织清单。Dev 严格按清单写,不自由判断。

### c. 双端 task md 之间字段 / method 签名 diff(协调端 audit 必做)

```bash
# iOS struct 字段
grep -E "^\\s*(let|public let|public var)\\s+\\w+:" Sources/Spec/<X>Client.swift

# Android data class 字段
grep -E "^\\s*val\\s+\\w+:" core-spec/.../<X>Service.kt

# 协调端机械 diff,不一致 → 派微 task 修
```

### d. task md 末尾"禁止"段必含

```markdown
- ❌ 自由判断 Spec 层组织(必按上方"双端 Spec 层组织清单",不自由发挥)
```

## How to apply

1. **协调端写双端 task md 前自检**:涉及 Spec / Service / 协议层组织的 task,**必先列双端清单**(类名 / 文件路径 / method 签名都明示)
2. **task md 模板加一段**:新增"双端 Spec 层组织清单"段,要求双端 task 共用
3. **协调端 audit 时机械 diff 双端字段 / method 签名**
4. **微 task** — 落后端补 Client 对齐另一端(先治标)

## 判定线

协调端写双端 task md,涉及 Spec / Service 层(协议接口 / 数据模型 / 文件组织)→ **必列双端组织清单,禁止 Dev 自由判断**。

## lint 状态

- 协调端写文档类,无静态扫描 → task md 模板"双端 Spec 层组织清单"段 + audit 机械 diff
