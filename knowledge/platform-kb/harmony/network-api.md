---
doc_id: "platform-kb/harmony/network-api"
container: platform-kb
platform: harmonyos
summary: "网络 / API"
---

# 网络 / API

## A. HttpClient instance pattern

```ts
import { HttpClient } from '../net/HttpClient';
import { ResultErr } from '../common/utils/Result';

// 标准调用:
const result: Result<T> = await HttpClient.getInstance().request<Object>({
  method: 'GET',  // 'POST' / 'PUT' / 'DELETE'
  url: HttpUrl.SOME_DETAIL,
  params: { itemId: id, type: type },
});

if (result instanceof ResultErr) {
  hilog.warn(LOG_DOMAIN.NET, 'TAG', 'err: %{public}s', result.error.message);
  return result;
}

// result 自动 narrow 为 ResultOk<Object>,result.value 可用
const dto = MyModel.fromJson(result.value as Record<string, Object>);
```

**禁** `HttpClient.get(url)` / `.post(url)` 静态调用(像 axios)— 该封装无此 API。

## B. 6 拦截器 chain(HttpClient 私构造已 wire)

HttpClient 私构造函数已 push 6 interceptor:
1. **AuthInterceptor** — 加 Authorization header
2. **LangHeaderInterceptor** — 加 Accept-Language
3. **BreadcrumbInterceptor** — 调用链 trace
4. **BusinessCodeInterceptor** — **envelope unwrap**(后端 `{code, msg, data}` → 自动取 data)
5. **LoggerInterceptor** — request/response log
6. **ErrorTransformInterceptor** — 转 Result<T>

新加 service 直接调 `HttpClient.getInstance()`,**勿** 重新 wire 拦截器。

## C. BusinessCode envelope

后端响应统一格式:
```json
{ "code": 200, "msg": "success", "data": { ... } }
```

BusinessCodeInterceptor 自动:
- `code == 200` → 取 `data` 作 `result.value`
- `code != 200` → 转 `ResultErr` + msg

业务层调用看 `result.value` 就是 unwrapped `data`,**不要再写 `result.data.code === 200` 之类**。

### C-bis. 非标准信封端点(裸响应)

少数端点**不走** `{code,msg,data}` 信封,直接返回裸 payload。实测:某些协议 / 隐私政策类端点返回**裸 HTML 字符串**。

- `BusinessCodeInterceptor` 对**非 object data 透传**(不解信封)→ 业务层 `result.value` 直接拿到裸字符串。
- 取值即用:`const html = result.value`,若为非空 string 即合法;否则报 `NetworkJsonParseFailed`。
- **不要**对这类端点写 `request<SomeDto>`,用 `request<Object>` 取裸值。
- 渲染该 HTML 字符串 → 见 `arkweb.md §A`(data-URI src,非 loadData)。

## D. deviceInfo / 应用版本 取真值

反馈 / 上报类接口常需带 `deviceInfo` 串(Flutter 侧格式 `<model>; <osVersion>; <appVersion>`)。鸿蒙端 API:

```ts
import deviceInfo from '@ohos.deviceInfo';                  // ⚠️ 非 @kit.*,bundleManager 未进 kit 体系
import bundleManager from '@ohos.bundle.bundleManager';

async function getDeviceInfoString(): Promise<string> {
  try {
    const bundleInfo = await bundleManager.getBundleInfoForSelf(
      bundleManager.BundleFlag.GET_BUNDLE_INFO_DEFAULT,
    );
    const model = deviceInfo.productModel ?? 'unknown';
    const sdkApi = deviceInfo.sdkApiVersion?.toString() ?? '?';
    const version = bundleInfo.versionName ?? '?';
    return `${model}; ${sdkApi}; ${version}`;
  } catch (e) {
    return 'unknown; ?; ?';
  }
}
```

**注**:`@kit.BasicServicesKit` 不直接导出 deviceInfo / bundleManager;`@ohos.deviceInfo` / `@ohos.bundle.bundleManager` 是 SDK 6.x(API 24)正确路径(Dev 实战发现)。

## D2. JsonHelper bool 强制

后端常返 `0/1` number 代表 bool(eg `isFavorite: 1`)。Dart `late bool` 自动 truthy coerce,**ArkTS 严格** number !== bool:

```ts
import { JsonHelper } from '../common/utils/JsonHelper';

static fromJson(json: Record<string, Object>): MyModel {
  const m = new MyModel();
  m.isFavorite = JsonHelper.optBool(json, 'isFavorite');  // 0/1 → false/true
  m.title = JsonHelper.optString(json, 'title');
  m.count = JsonHelper.optInt(json, 'count');
  return m;
}
```

| Helper | 用途 |
|---|---|
| `JsonHelper.optBool(json, key)` | 0/1/'true'/'false' → bool |
| `JsonHelper.optString(json, key)` | null safe |
| `JsonHelper.optInt(json, key)` | null safe |
| `JsonHelper.optDouble(json, key)` | null safe |
| `JsonHelper.reqXxx(json, key)` | 必填,缺则 throw |

## E. Result narrowing(必 instanceof)

详 `arkts-language.md §C`。ArkTS discriminated union 不支持反向 narrowing,**必 `result instanceof ResultErr` 判错**,不用 `result.ok`。

## F. Repository pattern

```ts
// data/repositories/X/XRepository.ts
class XRepository {
  private static instance: XRepository;
  static getInstance(): XRepository { ... }
  
  async fetchY(params): Promise<Result<YModel>> {
    const r = await HttpClient.getInstance().request<Object>({...});
    if (r instanceof ResultErr) return r;
    return new ResultOk(YModel.fromJson(r.value as Record<string, Object>));
  }
}
```

API endpoint name → 看 Flutter `http_url.dart` 真值,**对位** `common/constants/HttpUrl.ts` enum(去 `_URL` 后缀)。

## G. 新 endpoint 接入流程

1. grep Flutter `http_url.dart` 找 URL 常量真名
2. 加 `common/constants/HttpUrl.ts` 同名 const
3. 加 `data/apis/X.ts` method 用 HttpClient pattern
4. 加 `data/repositories/X/XRepository.ts` pass-through + 可选 cache
5. State / Page 调 Repository,不直接 HttpClient

## H. SSE / 流式 HTTP(spike 实证)

### H.1 真 API:`requestInStream`(SDK 6.1.x 实证)

❌ **假设 `http.HttpRequest.options.streamingMode + request()`** — 不存在
✅ **真 API**:`httpReq.requestInStream(url, options): Promise<number>` + 3 events

```ts
import { http } from '@kit.NetworkKit';
import { util } from '@kit.ArkTS';

const req = http.createHttp();
let dataEnded = false;

req.on('headersReceive', (h: Object) => {
  // content-type: text/event-stream;charset=UTF-8 → SSE
});

req.on('dataReceive', (data: ArrayBuffer) => {
  const chunk = new util.TextDecoder('utf-8').decodeWithStream(new Uint8Array(data));
  parseChunk(chunk);  // 见 H.4 SSE 切分
});

req.on('dataEnd', () => {
  dataEnded = true;  // ⚠️ 仅标记;不立即 finish — 见 H.2
});

req.requestInStream(url, {
  method: http.RequestMethod.POST,
  extraData: { recordId, type },
  header: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
}).then((status: number) => {
  if (status >= 200 && status < 300) finish('done');
  else finish('error', new Error(`HTTP ${status}`));
}).catch((err: Error) => finish('error', err));
```

### H.2 ⚠️ Lifecycle bug:dataEnd 早于 Promise resolve

**实测**:server 返 HTTP 500 + content-length 0(空 body)→ `dataEnd` 触发 → 约 1ms 后 `requestInStream.then(status=500)`。

- ❌ first-callback-wins(`dataEnd` 立即 `finish('done')`)→ HTTP 500 错误被吞,**误报 done**
- ✅ **state-machine**:`dataEnd` 仅标记,等 Promise resolve 拿 status 再 finish

### H.3 退化方案 — 短轮询(SDK 不可用时)

```
POST /某接口/createX 触发 server 端生成
loop:
  500ms timer → GET /某接口/getX?id=Y → 检 status:1/2=完成,0=生成中,-1=err
  空闲 timeout 30s 报错
UI 模拟"打字" → 每 polling diff 文本与上次,timed 拆字渲染
```

### H.4 SSE 切分 logic(参考)

```
per chunk → buffer += chunk text
  → split by '\n\n' → events[]
  → for each event:
       lines = event.split('\n')
       data = lines.filter(l => l.startsWith('data:')).map(l => l.slice(5).trim()).join('')
       try { obj = JSON.parse(data); onChunk(obj); } catch { /* partial, push back to buffer */ }
```

**实证于**:某 SSE streaming spike worktree(`data/apis/*.streamCreateResponse`)。

### H.5 SSE 调试根因诊断 protocol

Dev SSE 真机不通 / chunks=0 / parse fail 等 → 不要盲改代码,**先按 `sse-streaming-deep-dive.md` 跑 Phase 1 evidence checklist(10 项 hilog)**,evidence 收齐再走决策树定位 H1-H8 hypothesis。

**重要**:Flutter `HttpUtils.postStream` 与 Dev `streamCreateResponse` 已 1:1 对照 35 维 100% match → SSE 不通的根因 99% 在 server 真返响应内容 / token 实际值 / recordId 有效性等**运行时变量**,不在代码 layer。

详 deep-dive doc:`sse-streaming-deep-dive.md`(Phase 1 evidence + Phase 2 pattern compare 35 维 + Phase 3 8 hypothesis 决策树 + Phase 4 minimum repro spike)。

---

## I. WeChat SDK(`@tencent/wechat_open_sdk`,spike 实证)

### I.1 包 + 真名

- 真名:`@tencent/wechat_open_sdk`(腾讯官方鸿蒙 NEXT SDK)
- 版本:`^1.0.17`
- ❌ 假设 `@tencent-ai/wechat-ohos` / `fluwx-equivalent` — 不存在
- License:MIT
- ohpm / 官方接入文档:检索 "wechat_open_sdk ohos" 获取当前版本页

### I.2 module.json5 必配 3 处

```json5
{
  "module": {
    "querySchemes": ["weixin", "wxopensdk"],  // 1. WXApi.isWXAppInstalled 必读
    "abilities": [{
      "name": "EntryAbility",
      "skills": [
        { "actions": ["wxentity.action.open"] }  // 2. 微信回调 launch back action(原 home skill 保留)
      ]
    }]
  }
}
```

### I.3 SDK init 模块级单例(per cold start 一次)

```ts
// data/services/WXApiService.ets:
import wxopensdk from '@tencent/wechat_open_sdk';
export const WXApi = wxopensdk.WXAPIFactory.createWXAPI('<WX_APP_ID>');  // AppID 与 Flutter 常量三端共用
```

⚠️ **禁** client-side 引 appSecret(后端独占)。

EntryAbility 必加 `WXApi.handleWant(want, WXEventHandler)`(冷启 onCreate + 热启 onNewWant)。
业务订阅:`aboutToAppear` register / `aboutToDisappear` unregister。handler 内 `instanceof wxopensdk.SendMessageToWXResp` → 看 `errCode`:0=OK / -2=cancel / -3=fail / -4=auth deny / -5=unsupport。

### I.4 share image API

```ts
import { fileUri } from '@kit.CoreFileKit';
import wxopensdk from '@tencent/wechat_open_sdk';

async function shareImageToWeChat(ctx: Context, filePath: string, scene: number) {
  if (!await WXApi.isWXAppInstalled()) {
    promptAction.showToast({ message: '未安装微信' });
    return;
  }
  const imgObj = new wxopensdk.WXImageObject();
  imgObj.uri = fileUri.getUriFromPath(filePath);  // ✅ 用 fileUri,不传 ArrayBuffer / base64

  const msg = new wxopensdk.WXMediaMessage();
  msg.mediaObject = imgObj;

  const req = new wxopensdk.SendMessageToWXReq();
  req.scene = scene;  // WXSceneSession / WXSceneTimeline 是 `SendMessageToWXReq.WXSceneXxx` static readonly(非 enum)
  req.message = msg;
  req.transaction = `share-${Date.now()}`;

  await WXApi.sendReq(ctx, req);  // 返 boolean | Promise<boolean>,用 await 统一
}
```

### I.5 外部依赖(真拉起 3 项)

WeChat share 端到端 work 必满足:
- **D1**:测试设备装微信 6.0+(`hdc shell bm dump -n <微信包名>` 非 error)
- **D2**:应用市场真签 release 证书 + Profile(本地 DevEco 调试证书会被微信红条"Bundle ID 校验不通过",errCode 非 0)
- **D3**:微信开放平台「管理中心 - 移动应用 - 详情 - 平台信息」填 `Bundle ID = <应用包名>` + identifier 提审

**任一缺 → share 不可用,但 SDK 本身已 verified(plumbing 100%)**

**实证于**:某 WeChat SDK spike worktree(`services/WXApiService.ets`)。

---

## §S. WeChat WebPage 分享 — wxopensdk WXWebpageObject 1:1 pattern

**对位 Flutter `_fluwx.share(WeChatShareWebPageModel(webPage, title, description, thumbnail, scene))`** — WeChat 接收方看到 URL 卡(标题 + 描述 + 缩略图,tap 拉浏览器开 URL),不是 Image 卡。

**SDK 真签名(`@tencent/wechat_open_sdk` 1.0.17)**:
- `WXWebpageObject.webpageUrl` ← 目标 URL(必)
- `WXMediaMessage.mediaObject = WXWebpageObject;optional title / description / thumbData(Uint8Array ≤64KB)`
- `SendMessageToWXReq.message = WXMediaMessage / scene = WXSceneSession|Timeline / transaction = unique-id`
- `WXApi.sendReq(ctx, req) → boolean | Promise<boolean>`

**鸿蒙端实施**(`services/WXApiService.ets:shareWebPageToWeChat`):

```ts
export async function shareWebPageToWeChat(
  context: common.UIAbilityContext,
  webpageUrl: string,
  title: string,
  description: string,
  scene: number,
): Promise<boolean> {
  if (!WXApi.isWXAppInstalled()) return false;
  const webObject: wxopensdk.WXWebpageObject = new wxopensdk.WXWebpageObject();
  webObject.webpageUrl = webpageUrl;
  const message: wxopensdk.WXMediaMessage = new wxopensdk.WXMediaMessage();
  message.mediaObject = webObject;
  message.title = title;
  message.description = description;
  const req: wxopensdk.SendMessageToWXReq = new wxopensdk.SendMessageToWXReq();
  req.scene = scene;  // WX_SCENE_SESSION | WX_SCENE_TIMELINE
  req.message = message;
  req.transaction = `wx_web_${Date.now()}`;
  return await WXApi.sendReq(context, req);
}
```

**Phase 1 简化**:thumbData=undefined → WeChat 默认占位图。
**后续升级**:`Image.fetch(coverUrl) → PixelMap → image.packing JPEG ≤64KB` 真缩略图。

**对位 Image 卡分享**(`shareImageToWeChat`):本地 jpeg 文件 uri + WXImageObject.uri,详同 file §I.4。

---

## §POST-QUERY:Flutter `HttpUtils.post(URL, queryParameters)` 实际走 query string,非 body

**反抽规则**:Flutter `HttpUtils.post(URL, queryParameters: params)` 实际 POST + URL query string,不是 JSON body。Harmony 反抽必转 `query:` **不是** `body:`。

```
Flutter:  HttpUtils.post(URL, queryParameters: {itemId: 5585})
↓
HTTP:     POST /某接口/favorite?itemId=5585  (无 body)
↓
Harmony:  HttpClient.request({ url, method:'POST', query: {itemId: String(5585)} })
```

**反例**:Harmony 写成 `body: {itemId: 5585}` → server 查 query 找不到 `itemId` → 报 `msg=xxx id 不能为空`。1 轮 hilog 定位修复。

**审计 protocol**:
1. 反抽 Flutter `HttpUtils.post(URL, …)` → 看第二个参数:`queryParameters:` 转 Harmony `query:`(value 必 `String()`);`data:` 才转 `body:` JSON
2. server msg 含 "X 不能为空" / "X 不能为 null" 首查 body→query 漏转
3. Pre-ship: grep `body:` 全 API file,与 Flutter call site 交叉 verify

**例外**:少数 Flutter 也走 body 的端点(`api-contract` 标 `body:` 字样);默认按 query 反抽,例外另注。

## §TYPE-DISPATCH:收藏 / CRUD 类 API 隐藏 type 分支必 grep

**反抽规则**:Flutter favorite / unfavorite / detail / list 类 API 常按 `type` 分发到多 endpoint + 不同 param key,**不能假定单 endpoint 通用**。

**典型 type 编码**(示意,以实际 Flutter 分支为准):
- type==1: 某内容类型 A
- type==2: 某内容类型 B
- type==3: 某内容类型 C

**已知分发表(favorite,示意)**:

| type | Endpoint | param key |
|---|---|---|
| 类型 A 收藏 | `/A/favorite` | `aId` |
| 类型 A 取消 | `/A/unfavorite` | `aId` |
| 类型 C 收藏 | `/C/favorite`(注意路径命名可能与业务名不一致)| **`cId`** |
| 类型 C 取消 | `/C/unfavorite` | `cId` |

**反抽 protocol**:
1. 反抽 favorite/delete/list/detail 类 API → 必 grep Flutter call site `if (_type ==` / `if (type ==` 分发
2. Harmony API 函数 sig 设 `(id: number, type: number)`,内部按 type 分发 endpoint + param key
3. 协调端写 endpoint-section task md 必含**完整 type→endpoint→param key 表**,禁单 endpoint 假定
4. param key 严格 verify(各类型 id key 不可混)
