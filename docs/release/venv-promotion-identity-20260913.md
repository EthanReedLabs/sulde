# Venv promotion identity 修复

状态：源码修复与限定回归完成，已合 dev；未安装。基线 dev `4efb1aaaaa46a37c9296f306edf3bd523c3c2a68`。

## 冻结范围

只修复 `resource_preflight.py` 候选 promotion 对 venv 调用路径的误拒；新增专项测试，
不修改 receipt/grant 格式、不改变安装器环境校验、不执行生产安装、push 或 main 合并。
真实复现依据：[上轮安装报告](dev-acceptance-install-20260913.md)。

验收：真实 venv 回执可被 v1/v2 promotion 识别；不同调用环境、二进制变化、缺失解释器、
受损回执仍拒绝；安装前真实依赖漂移校验仍有效；专项通过后合 dev，归档证据并清理临时资源。

控制：原生 revision 2 receipt `97e8103f2fa7cfbed4bab489a160c306807898619ddc924bed65792197b5ca27`；
同会话 worktree handoff `64503d6456ad6358ce84516b4f85c5cb173620bfce5665942bc7aaeedcae667c`。
知识库 ap-0252 已全文回读；测试固定既有 Python 3.10.7/PyYAML，不使用未经检查的 PATH Python。

## 证据与问题

新增 7 个测试：修复前 4 个失败断言（v1、v2、relative、依赖测试的合法入口前提），
3.696 秒，exit 1；修复后 7/7，3.261 秒，exit 0。没有用 mock 替代解释器符号链接、
Python 环境探针和安装器 validate_python；只 mock 临时合成工件的 Git/宿主/制品身份。
这证明内部 Guardian 识别 → installer 校验路径，不声称生产 native Allow/安装已重测。

运行改动仅一处函数：保留 lexical absolute invocation 与 receipt 比较；真实 executable
继续用于既有 grant binding/二进制摘要。安装器重新探测 sys.prefix 与依赖字节的代码未改，
receipt schema、one-shot、CAS、真实 artifact 和 native proof 等门全部保留。
relative/PATH 查找只还原实际调用路径，不对全局 resolved_executable 做行为改造。

首次专项命令传裸模块名，官方 runner 从根目录无法导入，exit 1；随后用 --pattern 成功运行。
相关集成使用 tests.<module> 路径。该启动错误无生产写入，也不计入红回归失败数。

## 相关回归验收

官方隔离 runner 联跑 7 个模块：candidate promotion identity、candidate plugin、Python
environment preflight、Codex plugin install、Intent Guardian、maintenance candidate
preflight、control composition performance。365 项，348 通过、17 项既有 retired 规则
跳过，313.201 秒，exit 0；没有新增 skip，也没有放宽性能阈值。不是全仓发布套件。

本次新增 7 项无跳过；覆盖真实符号链接 venv、v1/v2、relative/PATH、同 binary 不同
调用路径、直接解释器、binary hash 不符、解释器缺失、坏回执和真实依赖字节漂移。
安装器回滚、进程中断恢复、native authority 和 Hook 正反边界也在相关套件中通过。
临时安装 fixture 不代表生产安装，当前已安装版本仍需后续正式发布才能获得此修复。

证据目录：`.sulde/public-export/venv-promotion-identity-20260913/`。其中 collected 日志
保留逐次轮询输出和 runner 终态，未包含首次 exec 的小段输出，不冒充完整会话日志；
`evidence.json` 记录精确测试入口、基线和退出码。提交前 `git diff --check` 无错误。

## 集成交付

源码提交 `f6fa07f` 已从干净任务分支 fast-forward 合入干净 dev；集成源码与已验证
任务树相同，没有冲突改写。证据已复制到长期 dev worktree 的同名目录，`diff -qr`
确认一致。随后仅更新本报告的交付状态，不改受测源码。

归档 SHA-256：

- evidence.json：`94f400279d9bb0de7968b5a75f47a3d53e576589ea6ee6c3afd1cbd91df9c381`
- red.collected.log：`014eb4478317bcb5f04728d7cf684cc9f71c1a8a4ac77dbb2c0122f482576b83`
- green.collected.log：`ecdeb49b86aff5c64b5ce23d8710faa911708e4c0466732b034b3cdee97fcb49`
- related.collected.log：`45bb78fb3b5fa52844f29b17350fbd8f074c2d4b6f2440b4d0e9c4c645f3644d`

本轮未安装、未 push、未合 main；主工作区既有 `.ua` 修改与 `.sulde/` 保留。
任务工作区清理由官方 release/finalize 流程记录，不以本报告预先宣称清理成功。

## 沉淀候选（Layer1，不直接入库）

- **问题类型/平台**：bug-fix、host-inconsistency / cross。
- **目标与用户预期**：合法 venv 发布链能完成，不因内部路径语义不一致频繁要求人工重试。
- **触发/症状**：prepare/verify 留下正确 venv 身份；promotion 的前置识别将其 resolve
  为底层解释器，再与调用路径严格比较，导致合法候选被拒绝。
- **已确认根因**：调用环境身份与二进制身份混为一个 canonical path；同一 binary 可以
  对应不同 sys.prefix/包环境。证据状态 verified（源码与真实 venv 红绿测试）；
  Windows 上的新运行行为、生产安装态复验本轮未观测。
- **已排除**：不需要削弱依赖校验或修改旧回执；仅将调用路径保留即可通过真实环境门。
- **一手证据**：上轮安装报告的 dva-host/dva-canonical 对比、本轮 7 个测试和源码 diff。
- **正确做法**：分开调用路径、二进制摘要、依赖环境；在每一层按自身语义比较，安装前再探测。

| 样本 | 内容 | 固定预期 | 原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | venv 验证通过，promotion 因解析符号链接后的路径不同误拒 | apply | 丢失了环境调用语义 | observed |
| 路由反例 | Python 路径不变，但依赖内容变更后正确拒绝 | skip | 真正环境漂移，不能宽免 | constructed，已回归 |
| 执行合格例 | v1/v2 保留 venv 调用路径，安装器验证通过且不改回执 | pass | 兼容和证据边界同时成立 | observed，本轮临时测试 |
| 执行失败例 | 仅比较底层 binary hash，放行另一个环境的旧回执 | fail | binary 相同不证明环境相同 | constructed，负例已回归 |

判重：症状检索 ap-0252 分数 0.500（测试解释器预检过晚），根因检索 ap-0250 分数
0.539（同名方法缺少对象类型证明）；两篇全文已读，均不同根因。建议独立 anti-pattern
候选，可关联 ap-0252，最终取号与入库由协调端完成。无共享 KB、索引或图谱写入。
上浮时删除路径、提交、日期和候选身份，保留通用的调用环境/二进制身份分离原则。
消费者：候选维护入口、安装器环境门和发布回归清单。
