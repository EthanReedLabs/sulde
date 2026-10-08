---
doc_id: "ap-0163"
container: anti-patterns
platform: android
summary: "0163 hide/show 宿主下 Fragment 生命周期与可见性解耦"
---

# 0163 hide/show 宿主下 Fragment 生命周期与可见性解耦

- **平台**:Android
- **复发次数**:1

## ❌ 错误

宿主通过 `FragmentTransaction.hide()/show()` 切换页签，却只在子 Fragment 的 `onPause` 停止媒体、轮询或埋点，并在 `onResume` 无条件恢复。切换页签不会触发对应生命周期；从上层 Activity 返回时，隐藏的 Fragment 又可能收到 `onResume` 并误恢复任务。

## 为什么错

- `hide()/show()` 改变的是可见性，不会让子 Fragment 跟随进入 `onPause/onResume`。
- 子 Fragment 的生命周期主要跟随宿主 Activity，因此生命周期活跃不等于页面可见。
- 播放、埋点、轮询和自动刷新等“仅可见时执行”的动作若只绑定生命周期，会在页签切换或上层页面返回时失控。

## ✅ 正确

- 在 `onHiddenChanged(hidden)` 中处理页签可见性变化，并复用与生命周期回调相同的停止/恢复入口。
- 在 `onResume` 中增加 `!isHidden` 可见性闸门。
- 同时验证页签切换、前后台切换、从上层 Activity 返回三条路径，确保行为一致。

## lint 状态

- ✅ 可做启发式 lint：若 `onResume` 操作播放器或轮询，而文件中没有 `isHidden` 或 `onHiddenChanged`，则告警。
- 人工 review：新增持媒体、轮询或持续埋点的页签时，检查生命周期与可见性是否双重门控。
- 关联：Fragment `hide/show` 可见性模型与宿主生命周期模型不可互换。
