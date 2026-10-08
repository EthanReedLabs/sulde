---
doc_id: "ap-0206"
container: anti-patterns
platform: none
summary: "排查容器配置时整屏打印了环境变量,输出进入会话/日志/粘贴板后数据库等凭据泄露,被迫全量轮换"
sedimented_by: auto
---

# NNNN — 排查容器配置时 dump 完整环境变量泄露凭据

- **平台**:跨平台(容器 / 运维 / 排障通用)

## ❌ 错误

排查容器配置问题时,为图省事直接打印完整环境变量,例如:

```bash
docker exec <container> env
kubectl exec <pod> -- printenv
cat /proc/<pid>/environ
```

容器环境变量里通常混有数据库连接串、API key、签名密钥等凭据。完整 dump 的输出会进入终端回滚缓冲、shell history、CI 日志、会话记录(含 AI 会话上下文与记忆库)、截图或粘贴板,等于把凭据写进了多个不可控的持久化通道。

## 为什么

- 环境变量是容器时代最常见的凭据注入方式,"配置"与"密钥"在 env 里物理混放,整屏打印必然连带密钥。
- 输出通道(日志 / 会话 / 剪贴板 / 终端录制)大多有持久化或同步机制,泄露后无法可靠删除,只能按"已泄露"处理。
- 一旦泄露,代价是全量轮换所有暴露凭据(数据库口令、API key、依赖方联动改配置),远高于排障时多打一条精确命令的成本。

## ✅ 正确

1. **只查目标变量,精确命中**:
   ```bash
   docker exec <container> printenv <VAR_NAME>
   kubectl exec <pod> -- sh -c 'printenv <VAR_NAME>'
   ```
2. **只需确认"是否设置"时,不打印值**:
   ```bash
   docker exec <container> sh -c 'test -n "$<VAR_NAME>" && echo set || echo unset'
   ```
3. **必须列多个变量时,先过滤再脱敏**:grep 变量名白名单,或对值做掩码(只显示前后几位),严禁未过滤的 `env` / `printenv` 全量输出。
4. **已经 dump 过一次**:按"凭据已泄露"处理——立即轮换暴露的全部凭据,并清理输出落点(日志 / 会话记录 / 记忆库)。

## 判定线

排障过程(含 AI 会话内执行的命令)出现无过滤的 `env` / `printenv` / `cat /proc/*/environ` 全量输出 = 违规;正确姿势是按变量名精确查询或先脱敏再输出。
