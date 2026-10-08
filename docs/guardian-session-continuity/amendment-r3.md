# 补充闭环 r3

用户确认后，当前会话原生 Allow 已应用 revision 3，receipt
`42abf0219f89f260f406ca60b403ba2d589e948650d201bb3ddefe67c70bc394`。
同一 intent；不复用旧安装 grant。不推送远端、不修改 main。

## 限定工作

1. 仅更新 Community 清单中既有 model-strategy 模板的内容摘要，不执行导出、不改变发布清单范围或模型策略。
2. 为四份既有测试的七处文本子进程补齐 UTF-8 和 replacement 解码，保持语义与命令不变。
3. 回读本会话单条多文件 apply_patch 的源事件与真实 Stop 审计，新增原型回归。不得虚构 PostToolUse 或成功结果。
4. 定向验证后冻结源内容；必要的完整集成测试仅运行一轮，保留前轮失败证据及已有适用性能证据。
5. 通过后提交并合并 dev，再为精确候选获取发布授权，执行候选校验、正式安装与当前会话验证。未通过不得切换生产。

## 已确认的事件结算事实

- 原事件：`d33400b1e4182ef727824c94`，call `exec-42c263cb-01ab-4eb0-aa88-34ed3e418acd`。
- 真实 Stop：2026-09-08T10:19:56.609844Z；追加 `sulde-guardian-turn-finalize-v1`，outcome=`inconclusive`，包含原事件完整摘要字段；intervention_ids 为空。
- 原 started 仍在；没有同一调用的 completed。该记录不是“执行成功”，也不是“没有发生写入”。
- 当前 open_events=0、pending_verifications=0；未手工修改或清除共享账本。
- 因此该单条记录的正规结算已由既有 Stop 路径完成，不新增一条重复恢复通道。具体为何缺少 Post 回调仍 inconclusive；本轮不将缺证据改写为已知宿主根因。

## 测试计划

定向：Community 全清单、编码静态门禁、四个受影响测试模块、多文件补丁 Stop 正反例。
回归要求：其他 session 的 Stop 不能结算该事件；当前 Stop 后新提案可生成；重复 Stop 不重复结算；原审计前缀 SHA 不变；未增加成功计数、grant 或外部效果。

知识库 ap-0242 的只读降级规则不适用于这次真实 local_write；仅借用“调用完成状态与外部效果状态正交”的边界，不把写入改为 read。

## 定向验收

- 82/82 通过，11.532 秒，证据 `targeted-20260908T103518Z-47c681a1`。
- 内容身份 `b817a254ec4b6e1893da796ca34024c62d04d4b115a44b9604bfe3c1e8f37378`；两项原有门禁均已通过。
- 多文件补丁正反例通过；真实 Stop 审计核验与构造回归分别保留，不互相冒充。
- 接下来对提交后的冻结树运行一轮完整集成测试；通过前不合并安装。

执行经验：`codex plugin list` 默认返回整个远端目录，输出过大。已从本地 Sulde 段确认当前 marketplace/version；后续查询必须限定输出，不重复拉取全目录作验收。
