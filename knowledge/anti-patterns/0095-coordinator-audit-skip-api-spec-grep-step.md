---
doc_id: "ap-0095"
container: anti-patterns
platform: none
summary: "协调端 audit root cause 凭症状推 Module 跳过 grep 接口契约 → 多轮 fix 失败"
---

# 0095 — 协调端 audit root cause 凭症状推 Module 跳过 grep 接口契约 → 多轮 fix 失败

- **平台**:协调端
- **复发次数**:1（多轮 fix 累积失败）
- **lint 状态**:⏳ pending（无法 lint 化，人工 checklist）

## 现象

后端返错误码 + 客户端视觉症状（如视频不播）同时出现时，协调端**第一反应是症状层 Module 内部诊断**（UI race / Player 渲染 / cache file extension / Button hit-test 等），**忽略后端错误码必先 grep 接口契约对照客户端请求参数**。

多轮 Phase fix 全失败:

| 轮 | 协调端推 root cause | 实际 root cause | 失败原因 |
|---|---|---|---|
| 1 | setMuted/setVisibility race | 不是 race | 凭症状推 Module 内部 |
| 2 | LazyVStack lazy cache 时机 | 不是 lazy cache | 加 log 但只覆盖 Module 不覆盖请求 body |
| 3 | AudioSession 静音键 | 部分（audio 路径） | 没区分症状 vs 后端错误码 |
| 4 | Button hit-test 被外层手势截 | 副作用（cache fix 后间接解） | 跳过 grep 接口契约 |
| 5 | dump 响应字段 | 不是字段缺失 | **只关注响应不关注请求** |
| 6 | dump 请求 body | ✅ **第一轮就该做** | 反应慢了多轮 |

最终 root cause:**client wire bug** — 会话 ID 用本地 random UUID 没接 server 返回 ID → 后端找不到 session 报错（详见会话 ID wire 反模式）。

## 根因（协调端 process）

### 1. 后端错误码出现时第一反应错

后端返的错误码 → 应推:客户端请求参数不符接口契约，或后端服务 bug。协调端反而推 Module 内部 race / Player 渲染 / Button hit-test — **这些不可能让后端返错误码**。

错把"症状（视频不播）"与"后端错误码"当独立问题处理。实际两者关联:client wire bug → 后端找不到 session → 报错 → 客户端 stream 异常结束 → 视频不播。

### 2. 跳过审单"grep 接口契约对照接口字段"步骤

多轮 fix 全跳过这一步。若第一轮跑 → 看到契约明确 `threadId = serverSessionId` → 立即知道 wire 是否对。配合 read 双端实现 → 看到一端对其他端错 → 第一轮就定位 wire bug。

### 3. 没识别"后端错误码出现"是诊断高 ROI 信号

Dev log dump 已实测看到错误码，那时协调端应立即让 Dev 加请求 body trace（看会话 ID 字段实际值）。协调端反而推"后端 LLM 链路报错 / 输入为空" — **推测不实证**。

### 4. 跨 Feature audit 缺失

多个 ViewModel 同模式，一端某 Feature **单独**修对（读了接口契约），知识没扩散到其他 ViewModel。协调端没在规则 / 反模式 / spec 文档明示"all wizard ViewModel 会话 ID 必接 server 返回 ID"。

## 修法（process 改进）

### 永久铁律

> **后端错误码（非 200 / errCode != 0 / 后端报错字符串）出现时，协调端必先 grep 接口契约 + PRD 文档对照客户端请求参数，不是先推 client 内部 race / Module bug。**
>
> 错误码出现时，**第一动作**:
> 1. `grep` 接口契约对应 endpoint 入参契约
> 2. Dev 加 trace dump 请求 body 实际值（不只响应）
> 3. 比对实际 body 字段值 vs 文档要求 → 一致 → push 后端;不一致 → 客户端 wire bug

### 触发场景识别

任一以下信号出现 → **立即跑 grep 接口契约 + read 双端实现**:

- 后端错误码 != 0（`errCode=xxxx` / HTTP 4xx 5xx / `error_message` 字段非空）
- 跨端表现不一（一端 work 一端不 work）
- 客户端 stream 异常结束（结束事件前无业务事件 / 仅报错快照）
- Dev handoff 推测后端 bug（协调端必先 verify 不是 client wire bug）

## Lint 候选

**无法 lint 化**（process 行为）— 人工 checklist:

- 协调端任 task md（尤其 fix 类）前自检:
  - [ ] grep 接口契约已跑?（粘贴命令输出）
  - [ ] read 双端实现 + git log 已跑?
  - [ ] 若涉及后端错误码 → trace 请求 body 实测已做?
- 任一未跑 → **不写 task md**

## 关联

- 代码层:wizard ViewModel 会话 ID wire bug（本反模式的代码层触发）
- runtime probe 实证驱动铁律（本反模式补强）
