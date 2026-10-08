---
doc_id: "ap-0064"
container: anti-patterns
platform: ios
summary: "0064 TCA `@Perception.Bindable` + `WithPerceptionTracking`…"
---

# 0064 TCA `@Perception.Bindable` + `WithPerceptionTracking` 必配对

- **平台**:iOS
- **复发次数**:4+

## ❌ 错误

view body 没包 `WithPerceptionTracking { }`,导致 state 变化不 track,单日多次同源复发:

- 输入框 view body 漏包 → computed property 读 `store.input` **不 track** → 永远初始 `""` → 按钮永远 disabled
- 子页 view 漏包 → `fullScreenCover` binding `$store.scope(state:...)` 不识别 state 变化 → modal 永远不弹
- 进度 view 漏包 → progress 圆环卡 0% 不动(reducer 更新多次但 view 不重渲)
- 协调端 perception fix task md 漏 sweep 全子 view

## 为什么错

TCA 1.x Perception API:
- iOS 17+ Apple `@Observable` macro 自动生成 tracking → 单 `@Perception.Bindable` 即可;
- **iOS 16.x 必手动包 `WithPerceptionTracking { ... }`**(body 内访问 store 的代码必须在 closure 内,否则 SwiftUI 不知道 state 变了)。

`@Perception.Bindable var store` 只是 binding 改造,**不替代** `WithPerceptionTracking`。**两者必同时用**。

iOS 17+ 模拟器测试自动正常(macro 接管)→ 真机 iOS 16 才暴露 → 协调端漏检。

## ✅ 正确

`view body` / `fullScreenCover closure` / `escaping closure` 内访问 store 的代码必包:

```swift
public var body: some View {
    WithPerceptionTracking {                     // ← 顶层包
        // body 内容
    }
}

// fullScreenCover(item:) closure 也要单独包(escaping)
.fullScreenCover(item: $store.scope(...)) { scopedStore in
    WithPerceptionTracking {                     // ← closure 内单独包
        ChildView(store: scopedStore)
    }
}
```

**判定线**:iOS task 涉及 SwiftUI view + `@Perception.Bindable var store` → grep `WithPerceptionTracking` 必 ≥ 1 命中(view body)+ 每个 escaping closure 内单独包。

## lint 状态

- 协调端 task md 加"`@Perception.Bindable` + `WithPerceptionTracking` 配对自检"硬约束;
- 自动 lint:
  ```bash
  for view in $(find Sources -name "*View.swift" -type f); do
      bind=$(grep -c "@Perception.Bindable" "$view")
      track=$(grep -c "WithPerceptionTracking" "$view")
      if [ "$bind" -gt 0 ] && [ "$track" -eq 0 ]; then
          echo "❌ $view — Perception 配对漏"
      fi
  done
  ```

## 关联

- "协调端凭印象"父类 — 子 Feature View sweep 漏多次
- "handoff escalation 漏 sweep" — Perception fix escalation 自承"子 view sweep 候选" 漏派后续
- 五大 escaping closure 触发点(Binding / `.sheet` / `ForEach` / `let store` / `.overlay`)各需单独包
