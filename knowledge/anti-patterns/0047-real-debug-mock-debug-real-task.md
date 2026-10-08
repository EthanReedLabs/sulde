---
doc_id: "ap-0047"
container: anti-patterns
platform: none
summary: "0047 跨端默认 Real 路径不对称(一端 DEBUG 默认 Mock,另一端 DEBUG 默认 Real)→ 同…"
---

# 0047 跨端默认 Real 路径不对称(一端 DEBUG 默认 Mock,另一端 DEBUG 默认 Real)→ 同 task 验收结果迥异

- **平台**:协调端(双端对齐类) + 双端实施
- **复发次数**:1

## ❌ 错误 — 问题描述

双端业务层接 Real Service / Client 后,**DEBUG build 默认走哪条路径**两端不对称:

- iOS:`MarketConfig.current` 默认 `.dev` → `registerDevDependencies` 把多个 Client **全置 Mock** → 业务层 onAppear 调 mock client 返桩数据,**永不发网络请求**
- Android:DI module 默认 `add(realAdapterModule)`,**始终生效** → 业务层 onAppear 调 realAdapter 真发请求,DEBUG 也直接联通 staging-api

→ 双端业务层接 Real,**Android 实测 OkHttp logcat 看到 staging-api 200 OK**,iOS console **0 接口请求**(因为 DEBUG 默认 Mock)。同一份"业务层接 Real"task 双端验收结果迥异 — Dev 困惑、协调端误判、用户错以为 iOS bug。

## 为什么错(真因)

- iOS 历史包袱:此前没接口,DEBUG 默认 Mock(开发体验快不挂网络),启动 arg 才显式启用 Real
- Android 后建:从一开始就默认 Real(realAdapter 始终 add)
- 业务层接 Real 时,只补了 RealAdapter 实现,**没拉齐两端默认路径** → Spec 组织对称只管接口契约,默认行为对称是另一条,两条都失守一条就出问题

## ✅ 正确 — 修法

业务层默认 Real,Mock **只在 2 类场景保留**:

| 类别 | 例子 | 原因 |
|---|---|---|
| 后端真没接口 | Feature 层 client(Spec 没对应 endpoint) | 不属"有接口不用",合理保留 |
| 模拟器物理限制 | paymentClient(IAP 沙盒)/ pushClient(APNs/FCM)/ uploadClient / downloadClient / shareClient(Share Intent) | simulator/emulator 不支持真实 push/file/IAP |

**两端 DEBUG/RELEASE 默认行为必须对称**:

- iOS:删 `Market.dev` case + `registerDevDependencies` 全块,DEBUG / RELEASE 都走 `registerLiveDependencies`,删 launch arg gate(不再需要)
- Android:dev override module 仅保留物理限制类 Mock
- **Mock Adapter 类保留作 TCA testValue / 单测**(那是 testValue 路径,不是 liveValue,不影响默认行为)

## 判定线

修完后跑 grep 自检:

```bash
# iOS:不应再有 Market.dev case / live gate
grep -rn "Market\.dev\|case .dev\|LiveAdapters" Sources/<App>/  # 应 0 命中

# Android:dev override module 仅保留物理限制类
grep -A 5 "devOverrideModule = module" app/src/main/.../<DI>.kt
```

实测验证:DEBUG 启动后 console / logcat 看到 staging-api 请求(public 200 / 鉴权 401)— 双端都看到 = ✅。

## 反例 vs 正例

| 场景 | ❌ 错误 | ✅ 正确 |
|---|---|---|
| 双端 DEBUG 默认行为 | iOS Mock / Android Real | 都 Real,Mock 仅 testValue + 物理限制豁免 |
| 启动验证方式 | iOS 必须传 launch arg;Android 直接跑 | 两端直接跑即可,无显式开关 |
| Mock Adapter 类位置 | 业务层注入 mock | testValue / 单测注入 mock(liveValue 走 Real) |

## 关联

- Spec / Service 组织对称是接口契约对称;本条是默认行为对称;两条合起来 = 双端零分化
- 跨端验收对照表必含"两端默认 build 行为一致"项
- Real 是默认数据源,Mock 是 fallback(且仅 2 类场景豁免)

## lint 状态

- iOS/Android:⏳ TODO(grep 默认 DI module 是否对称)
