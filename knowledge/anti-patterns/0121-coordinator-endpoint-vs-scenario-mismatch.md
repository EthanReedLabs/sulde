---
doc_id: "ap-0121"
container: anti-patterns
platform: none
summary: "0121 协调端只看 endpoint 名 / schema 字段,漏看章节标题 / 场景定位"
---

# 0121 协调端只看 endpoint 名 / schema 字段,漏看章节标题 / 场景定位

- **平台**:协调端
- **复发次数**:1

## ❌ 错误

协调端 grep API 文档判定"这是真链路"时:
- ✅ 看 endpoint URL — 命中
- ✅ 看响应 schema 字段(如 `outputVideoUrl: string?`)— 看起来像目标 URL
- ✅ 看请求 schema 字段 — 语义对得上
- ❌ **没看章节标题**(如"某手动编辑场景的渲染接口")— 这是编辑场景,非自动流程
- ❌ **没看用途列 / 流程图**("获取最近保存的配置" — "保存"暗示是用户编辑过的配置)

基于"字段语义看起来对"直接写 fix task md wire 这个 endpoint → 真机三连 404(not found / invalid)。

## 为什么错

- API 文档**章节按场景组织**:同一字段名在不同章节代表不同语义(列表场景的 `videoUrl` = 已合成成品;编辑场景的 `outputVideoUrl` = 用户编辑过的配置才有)。
- 协调端**字面 grep 命中 endpoint + schema 字段名**就以为 = 真链路,**没看章节标题就是场景定位**。
- 自动流程 ≠ 手动编辑场景 — 同 API 域名下,**场景不同 endpoint 不通用**。
- 真机三连失败 + msg 是"not found / invalid"= **99% 是场景错位**(不是后端 bug,不是 Dev 实施错)。

## ✅ 正确

1. **baseline grep 带章节上下文**:命中 endpoint 后必 `grep -B 20 -A 5` 看上下文,确认:最近的章节标题是什么场景?接口表"用途"列写什么?流程图(若有)显示这个 endpoint 在什么场景被调用?
2. **文档场景 vs 业务场景 cross-verify**:章节标题 / 流程图位置 / 触发条件 / 必填字段 / 真机验证 五维对照,**两者不匹配 → 不是真链路**,即使 schema 字段名相似。
3. **多场景 endpoint 共存时的 verify 链路**:先看章节标题 narrow 场景 → 看推荐对接流程 narrow 调用顺序 → grep 已 wire 代码反推现有用途 → 多个 candidate 选不准时**必抓 prod 流量实证**(抓包),不凭文档字面推。
4. **task md / 推单 doc 引用 endpoint 时必同时写章节号**(`§x.y 标题`),不只写 URL。

## lint 状态

⏳ pending — 软警告:task md / 推单 doc 引用 API endpoint 但缺章节定位上下文 → 提示可能漏看 endpoint 所在章节场景。需协调端 baseline grep 加"章节标题 / 场景上下文必读"。

## 关联

- 协调端漏读文档新版(同源)
- API 文档 ≠ 接口真值(升级为"API 文档章节定位 ≠ 业务场景"补一层)
- 凭印象不查实证(同源)
