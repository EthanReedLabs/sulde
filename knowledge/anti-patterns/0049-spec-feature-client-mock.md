---
doc_id: "ap-0049"
container: anti-patterns
platform: none
summary: "0049 Spec Feature 层抽象 Client 留 Mock 不易察觉 → 主线流量 0 真后端命中"
---

# 0049 Spec Feature 层抽象 Client 留 Mock 不易察觉 → 主线流量 0 真后端命中

- **平台**:协调端(review 类) + 双端实施
- **复发次数**:3

## ❌ 错误 — 症状

Real Adapter 全量接入后,多模块 Spec Client 都接通,但**App 启动后 console log 仅看到 mock URL DNS 失败,0 staging-api 命中**。用户感受:首屏没数据。

## 为什么错(根因)

`registerLiveDependencies` 内仍有:
```swift
values.homeClient = mockHomeClient()       // ← Home 是默认入口 Tab
values.discoverClient = mockDiscoverClient()
values.taskCenterClient = mockTaskCenterClient()
```

理由是"后端没有该专用 feed endpoint" — 但 **首屏是 App 默认入口**,等同于"主线流量 0 真后端命中"。Feature 层抽象 Client(`HomeClient` / `DiscoverClient`)**没有直接 endpoint 不代表无法接通** — 完全可以用 backend Client 做 Adapter 包装。

## ✅ 正确 — 修法

新建 Feature 层 Real Adapter 包装 backend Client:

```swift
extension HomeClient {
    static func live(backendClient: BackendClient) -> HomeClient {
        HomeClient(
            fetchFeed: { tab in
                let page = try await backendClient.getList(...)  // 复用公开端点
                return page.list.map { $0.toFeedItem() }
            }
        )
    }
}

// DependencyRegistration:
values.homeClient = HomeClient.live(backendClient: values.backendClient)
```

## 判定线

`registerLiveDependencies` 内出现 `mockXxxClient()` / `MockXxxAdapter.client()` 时,review 必问:

| 问题 | 判定 |
|---|---|
| Q1:这个 Client 是用户感知层级吗?(是否在主线 Tab / 默认入口 / 首屏) | 是 → 高警觉 |
| Q2:有 backend Client 可以包装代替吗? | 有 → 必须包装,不能留 Mock |
| Q3:真没接口且非主线 — 显式说明 | 否则 → 违规 |

**协调端 review checklist**(写 task md / 验收 handoff 必查):
- 每个"留 Mock 的合理理由"必须显式说明"用户感知层级"(主线 / 二级 / 边缘)
- 主线 Tab Mock = 红线 — 必须找 backend Client 包装

## 协调端 sweep 加固

- 写双端 task md 时,涉及 Feature 层任何 Mock 主线引用 = **红线**,task md 必修(不可遗留)
- Spec / Feature 层 `Mock*Adapter` / `mock*()` 函数被主线引用即触发(grep 主线 reducer / vm / fragment / view)
- 周期审计每周一次:`grep -rn "mock\|Mock" Sources/Feature*/ feature-*/ | grep -v "Mock.*Adapter\.swift\|Mock.*Source\.kt\|//.*mock"` 看主线引用

## lint 状态

- iOS:⏳ TODO(扫 `registerLiveDependencies` 内 `mockXxxClient`,交叉 page-relation entry 入口判断)
- Android:⏳ TODO(同上,扫 `realAdapterModule` / `devOverrideModule` 内 `Mock*`)

## 关联

- 默认 Real 路径对称 — 本条是其盲区扩展(默认 Real 后仍可能 Feature 层留 Mock)
- 协调端凭印象 — 写"upload/download/push/share/home/discover 保留 Mock 合理"时,**必须区分用户感知层级**,不能一刀切
