# Python 字符串方法误拦截修复报告

状态：**开发与隔离验收通过；生产尚未更新**。

修复提交：`e4e50affd7dc5de1a7bb72881dc364daf7cd15e5`。
基线：dev `f034452def541d2f63660a19ec5725b87b9362e1`。
分支：`task/guardian-python-dataflow`。机器证据：[EVIDENCE.json](EVIDENCE.json)。

## 根因与修改

原证明器只识别字面量及单次顶层赋值：没有 Path.read_text/read_bytes
返回类型，不识别顺序重赋值，不进入推导式作用域；无关 import 还会让整段
变量证明失效。因此正常字符串 replace 被当成无法证明类型的文件替换方法，
升级为 `unresolved-destructive-receiver` 硬拒绝。

新增独立的、无 IO 的有界前向证明器，原字面量/list.remove 证明保持不变：

- 按 Python 求值顺序传播精确 str/bytes 类型，先读 RHS 再更新赋值。
- 识别明确 pathlib 构造与 read_text/read_bytes 返回值；实际 write_text/write_bytes
  继续是 local_write，不把整条读改写命令标成只读。
- 识别字面字符串列表/元组上的单生成器、无过滤条件的 eager 推导式局部变量。
- 未知调用、属性访问、命名空间修改、未知重绑定和控制流边界使借用事实失效；
  不传播到 function/lambda/generator 等延后执行作用域。
- 所有其他调用和参数仍由原效果分类器独立检查；真实 Path.replace、删除以及
  未证明的接收对象继续保留拦截。Pre 拒绝与任务暂停的既有分离语义不变。
- 新增证明只在尚有未证明 replace 时运行，设置 AST 数量和表达式深度上限，
  每次分析使用独立事实集合，不继承别的调用/会话类型信息。

## 验收结果

共运行 **390 项：373 通过、17 跳过、0 失败**，测试耗时 128.838 秒。
这些是影响范围回归，不是全仓全量测试。包括完整 intent_guardian 模块、
资源标识、状态/收口、组合命令、Hook bridge、性能门禁、发布清单以及本次正反样本。
运行绑定修复提交，前后源码摘要均为
`d4870ed33c3d59d902004a73a084ae620be91ba64435efeaaf59a21ed45ef458`。
本报告和 EVIDENCE 是之后增加的文档，不将其伪装成重新跑过全量的 exact HEAD。

真实链使用官方临时 artifact/安装入口、新进程、Codex CLI 0.153.4 app-server、
unified exec 和实际 Hook。模型侧为本地确定性响应夹具，**0 次外部模型请求**。
没有直接调用 normalize/observe 伪造 live proof，也没有修改生产 registry。

| 实际动作 | 结果 |
|---|---|
| 本地文件 read_text → replace → write_text | 实际从 before 改成 after，Pre 事件为 local_write |
| 字面键名推导式 replace | 实际输出 verified-count 等转换结果，原生 Pre Hook 完成 |
| 标准删除 canary | 执行前拒绝，独立 finalize 验证后清理 marker |
| 真实 Path.replace | 执行前拒绝，源文件保留，目标文件不存在 |

物质 Pre 事件均核对 provider/session、live_verified、loaded_module_generation
和 artifact_generation；标准 proof 为
`2eb7708620a0b0551e68a4562e6624e00af0d4e80bf694146079e50434ef7362`。
成功只读动作按现有轻量路径不写物质审计行：使用真实 Hook 通知及执行输出证明，
不为凑验收伪造事件。标准 rm probe 按当前契约记录 local_write 并保留 destructive
防护，所以另加真正的 Path.replace 负例验证 destructive 分类。

### 性能

绑定同一解释器、基线和修复文件摘要的采样：文件读改写分类中位数
145.75 → 170.16 微秒（新增 24.41 微秒），键名推导式
81.94 → 99.87 微秒（新增 17.93 微秒）。全部六类样本通过预先设置的
新增分类开销 500 微秒、规范化开销 10 毫秒预算。
完整 normalizer 采样受机器并发和固定系统开销影响，不能把观测中的下降
解释为本次代码带来了整项任务加速。此次收益是避免错误拒绝/重试，
并非移除了控制面的全部固定成本。

## 保留边界与未完成的外部阶段

- 不支持任意 Python 类型推断；未知 iterable、混合类型、过滤式、延迟作用域
  仍可能无法证明。这次没有按方法名一律放行。
- `from pathlib import Path as P` 的字符串调用已获证明，但另一个既有
  写入路径提取器仍可能输出 `unresolved_local_write`；该形态不再有本次
  destructive-receiver 硬拒绝，不把它虚报成完整的 typed-path 证明。
- Vario 形态仅证明局部键名 replace，整段含动态模块调用的脚本仍为 unknown，
  不把其他代码顺带认定为只读。
- main、dev、Git/Figma 规则、业务文件、生产 generation 和共享知识库未修改。
  未合并、推送或正式安装；其他终端仍使用旧生产代码，须在后续批准的安装后生效。
- Windows native 验收未执行；不宣称跨平台正式发布完成。

## 实施复盘（包含 Agent 自身问题）

所有失败运行及日志摘要保留于 EVIDENCE 的 runs；失败均为不可复用成功证据。
原始日志和解释器完整身份留在任务本地 `.sulde/data/guardian-python-dataflow/`，
不提交业务日志、完整 prompt 或生产账本。

1. **verified / 测试基础设施**：首次官方隔离器在宿主沙盒内不能启动 sandbox-exec。
   请求原生批准后在外层执行官方隔离器；未关闭生产写入保护。
2. **verified / 打包准备**：新模块未加入 Git index 时，按 Git 清单打包的 artifact
   缺少该模块。先暂存精确任务文件，再重做隔离打包；没有扩大发布清单或改生产 cache。
3. **verified / 测试夹具**：候选环境会清除外层隔离标识；在替换环境之后读取标识，
   导致 macOS 嵌套沙盒、正例 exit 71。按现有官方 canary 用法在替换前捕获标识修复。
4. **verified / 宿主协议假设**：CLI aggregatedOutput 可为空，输出从 delta 通知到达；
   读取流式通知。只读快路径没有物质审计行、标准 probe effect=local_write，
   均按真实契约调整断言，并额外保留真实 Path.replace 负例，未降低安全验收要求。
5. **unresolved / 相邻范围**：构造器别名的精确本地路径提取限制如上。它是旧边界，
   不纳入本次类型证明修复，也不删除其 uncertainty。
6. **inconclusive / 临时清理**：一次失败夹具收尾出现 Git objects 目录仍在写入导致
   Directory not empty；后续成功验收未复现，未据此修改生产清理器。

## 沉淀候选（单写者入库前的 Layer1 问题卡）

- 问题类型：bug-fix / host-inconsistency。
- 用户意图：普通字符串处理由 Agent 正常执行；实际文件破坏动作继续受控。
- 触发：多个业务会话用 Python 做文本读改写或字面键名推导式。
- 症状：同名 replace 被归入未证明的文件操作，PreToolUse 连续硬拒绝。
- 根因：证明域缺少顺序赋值、可信读返回类型与局部 comprehension 类型绑定。
- 排除：不是浏览器版本、会话串线或单纯重启问题；基线源码与已安装证明器一致。
- 证据状态：verified。来源为原始事故调用的脱敏形态、基线/修复对比、真实候选执行链。
- 做法：补有界、局部、可失效的类型证明；不改总策略、不推断整个脚本只读。
- 路由正例（observed，apply）：read_text 后 string.replace 被误拒绝；同名异义且
  具有可验证的 builtin 返回类型。
- 路由反例（constructed，skip）：Path.replace 或 receiver.replace 类型未知；
  不具备字符串证据，不能应用放行结论。
- 执行合格例（observed，pass）：真实文件变更成功且仍记录 local_write，真实文件
  替换负例 Pre 拒绝，两种发布身份一致。
- 执行失败例（constructed，fail）：将所有 replace 标 read，或者只证明 Hook
  能运行/能拒绝，却没验证真实业务正例执行。
- 上浮前泛化：删除项目名、会话/事件 ID、私有路径与本次提交标识。
- 可复用内核：同名方法的风险不能代替对象类型；成功与拒绝两侧都需要真实宿主样本。
- 建议容器：anti-patterns；消费者：效果分类器、Hook 集成验收、review checklist。
- 采用技能的影响：intent-guardian 冻结源码和安装边界；kb-search 的 ap-0243
  仅用于区分效果/拒绝/暂停；dispatch-task 生成当前宿主的任务文本，不切换模型。
