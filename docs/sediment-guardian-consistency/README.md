# Guardian 已验证候选沉淀

本批以协调单写者身份，从 `dev@11c8f9063da32606caeccd4355be8d8d5b44b9c8`
创建隔离分支 `feat/sediment-guardian-consistency`。只修改知识文档、索引、变更记录和
本目录证据；不修改运行逻辑、安装代际、共享数据库、main/dev，也不推送。

## 取舍与来源

检查发现 8 段候选，Python 发布摘要与开发报告重复，归并为 7 个主题。
原始 Layer1 问题卡保留在来源报告，不复制为第二套事实真源：

| 主题 | Layer1 来源 | Layer2 去向 | 证据与边界 |
| --- | --- | --- | --- |
| 同名方法对象证明 | [Python 报告](../guardian-python-dataflow/REPORT.md) | [ap-0250](../../knowledge/anti-patterns/0250-method-name-risk-without-receiver-proof.md) | 基线对比、候选真实宿主正反链；局部类型证明不等于整脚本只读或完整路径证明 |
| 幂等登记及独立验证 | [记忆报告 A](../guardian-memory-consistency/REPORT.md) | [登记契约](../../knowledge/work-model/idempotent-registration-verifier-contract.md) | 十次调用一条关系、丢 Post 后只读结算；不泛化至任意外部写入 |
| 可选记忆依赖投影 | [记忆报告 B](../guardian-memory-consistency/REPORT.md) | [ap-0251](../../knowledge/anti-patterns/0251-optional-enrichment-invalidates-unrelated-approval.md) | 明确无依赖、限定本地效果、无 grant；不清债、不继承权限 |
| 隔离与续接组合 | [记忆报告 C](../guardian-memory-consistency/REPORT.md) | [显式续接](../../knowledge/work-model/session-isolation-explicit-continuation.md) | 真实 CLI、隔离人工决定夹具；不写成生产真人点击 |
| 集成后的多对象锁 | [回执报告](../guardian-receipt-consistency/REPORT.md) | [所有权与回执锁](../../knowledge/work-model/ownership-aware-receipt-locks.md) | 真实文件锁及中断恢复；生产故障因果仍未确认 |
| 实际解释器预检 | [回执报告预检卡](../guardian-receipt-consistency/REPORT.md) | [ap-0252](../../knowledge/anti-patterns/0252-test-interpreter-preflight-too-late.md) | 错环境快速失败、支持环境复验；不是跨平台启动结论 |
| 发布覆盖、执行权、代际 | [发布报告](../guardian-memory-consistency/RELEASE.md)、[Python 发布](../guardian-python-dataflow/RELEASE.md) | 并入[证据门禁](../../knowledge/work-model/evidence-gate-contract.md)及[字节与代际验证](../../knowledge/work-model/canonical-byte-authority-self-hosted-verification.md) | 复用覆盖不等于复用 grant；真实中间事件必须绑定两种代际 |

六篇新增、两篇实质并入；新编号从当前全量目录末号 0249 续为 0250–0252，
不依据落后的分平台目录末号回填。Layer2 已移除项目、人物、私有路径、会话、提交、
grant 和 receipt 标识；代码中的通用 API 名保留。本文及原始报告承担内部溯源，
不进入知识语料索引。

## 判重依据

本轮症状与根因各检索一次，完整查询和结果见 [dedup-search.json](dedup-search.json)。
采用前已回读相关原文；以下是人工语义核对，不按相似度自动合并：

| 命中 doc_id / 标题 | 本轮分数 | 判定理由 |
| --- | --- | --- |
| ap-0243 / 控制命令组合违规被误升级为破坏性暂停 | 0.829245，skip | 是组合资格与效果/暂停耦合，不是 receiver 类型证明；不同根因，不并入，也不沿用其过时的组合禁令 |
| work-model/canonical-byte-authority-self-hosted-verification / 规范化字节权威与自托管验证 | 0.500000 | 发布中间事件双代际是自托管验证的深化，直接并入；数据库幂等登记则是不同契约问题，新增互链 |
| ap-0181 / 长寿命会话跨越插件热更新持有悬空路径 | 1.000000 | 同样出现会话症状，但根因是缓存路径存续，不是独立合同缺少续接转换 |
| work-model/evidence-gate-contract / 证据门禁的来源、格式与时序契约 | 0.500000 | 可证明覆盖下的测试复用与独立效果证据是同一工作模型的深化；锁所有权仍需独立条目 |
| ap-0235 / launcher 规范已更新，但已生成包装器仍是旧壳 | 0.500000 | 是生成器与投影漂移，不能代替测试入口选择错误解释器的根因 |

图谱可选增强与其他异步增强、环境预检与生产/验证环境差异等既有知识，
主题相关但根因或容器不同；没有把“相关”当成“同一篇”。已有条目的原样本保留，
发布新变体逐项保留 observed/constructed 标签。

## 明确保留、不上浮为事实

- 旧维护 helper 的具体分类原因、后台 degraded 根因和恢复扫描内部成本分布。
- Python 构造器别名的精确写入路径提取限制，不宣称本批或原类型修复已解决它。
- 单次临时目录清理异常，缺少稳定复现。
- 并发锁的历史生产事故归因；目前只证明集成源码缺口与隔离回归。
- 不把“失败全量＋定向复验＋范围等价证明”改写成最终 HEAD 全量全绿。
- 当前知识 ap-0243 的旧组合策略边界需要另行维护，本批未扩大为控制策略修复。

## 校验方法

实际使用已核验的 Python 3.10.7；检索使用既有 KB venv。全程禁写字节码，不安装依赖。
任务私有索引通过 SQLite 只读 backup 初始化，模型缓存使用本地 copy-on-write 副本；
venv 仅只读复用。源码自带 CLI 从当前 Git checkout 建索引，不使用已安装 runtime
的旧语料，也不改变生产索引。所有派生数据在本任务 `.sulde/kb/`，不提交到 Git。

顺序为：

1. 精确暂存知识文件，使 Git 语料清单可见新增文件。
2. frontmatter lint、sedimentation lint、目录生成。
3. 生成并独立校验语料 MANIFEST，再构建私有检索索引。
4. 固定本批 32 条独立改写问题，要求目标语义进入 top-3，所有 skip 必须 top-1；
   同时复验已有 20 条基准，不降低阈值、不改变检索代码或问题文本。
5. 运行知识工具定向测试及对象证明、记忆契约、续接/真实文件锁的消费者回归。
6. 脱敏、关联、源码差异、目录/清单一致性及提交状态检查。

发布真实宿主证据复用来源批次的不可变记录，本轮没有重跑安装或把文档测试冒充
当前生产 canary。此前检查已对三批 43 份归档测试日志重新计算摘要，全部匹配。

## Agent 实施问题记录

| 问题 | 处理与证据状态 | 保留方式 |
| --- | --- | --- |
| 第一轮私有索引构建发现 MANIFEST 摘要仍是旧语料 | verified：重新生成并校验清单后构建通过；不是删除校验或改用旧缓存 | 验证顺序已补清单步骤，首次失败不标为可复用成功 |
| 首轮改写查询 30/32，记忆 skip 与代际 pass 极性错误 | verified：仅修改知识样本，使任务对象和安全拒绝的验收含义明确；算法、门槛、问题不变 | [首轮结果](paraphrase-run-1.json)永久保留为失败 |
| 第二轮 31/32，记忆排除仍错误 | verified：继续聚焦“图谱自身是任务对象”的边界，复验全部问题 | [第二轮结果](paraphrase-run-2.json)保留，不覆盖首轮 |
| 原任务是只读推送收尾，文档范围不能由 Agent 自动扩张 | 按原生当前会话确认，批准后的 r3 才开始写知识；未冒充 Agent 自主批准 | 受宿主原生回执约束，未复制摘要给用户 |
| 宿主报告保存了精确 native-decision 命令前缀 | observed / 因果 inconclusive：本轮没有传 prefix_rule；命令仍受一次性事务防重放约束 | 保留为宿主审批行为观察，不修改权限配置或推断根因 |

## 技能影响

sediment 决定了单写者、先判重、六新增两并入、脱敏、四类样本和隔离提交；
kb-search 要求回读原文并拒绝把高分误命中当同根因。intent-guardian 将文档写入与
上一轮完成锚分开，使用原生批准限定范围，没有安装、推送或复制旧任务授权。

最终结果与内容摘要见 [EVIDENCE.json](EVIDENCE.json)。
