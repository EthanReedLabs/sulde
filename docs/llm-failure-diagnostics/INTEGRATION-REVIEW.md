# 集成审查及补齐

日期：2026-09-23。审查者：当前 Codex Agent；未启动额外 Agent 或付费模型调用。
结论：本次定向审查发现的两项问题均已修复，可进入提交审查；尚未提交/合并/安装。
这不是独立人员复核或生产发布验收。

## 已关闭问题

### R1：模板解析异常仍保留原始 context

- 位置：`auto-distill.py:run_llm`、`self-repair.py:run_command_template`。
- 原代码在 except 内 `raise ... from None`，仅隐藏标准 traceback 的上下文显示，
  不清除 `__context__`。合成 ValueError 中的秘密哨兵仍可从异常对象访问。
- 不夸大为已证实的生产秘密外泄：当前真实 shlex 引号错误为固定消息；风险在于
  异常链保留以及其他诊断消费者继续遍历它。
- 修复：模板解析失败先收敛为空参数，在 except 外产生固定 startup_failure。
- 新测试覆盖两个入口的合成秘密异常、真实未闭合引号、空命令，确认
  context/cause 为空且 subprocess 未启动。未改变成功执行路径。

### R2：scheduler 最小运行 fixture 缺少新 helper

- 位置：`tests/test_scheduler_entrypoints.py`。
- 原 fixture 只复制 auto-distill.py 和 command_template.py；新增 runpy 依赖后，
  macOS 系统 Python 的真实 --help 启动发生 FileNotFoundError。
- 修复：明确复制 llm_diagnostics.py，保持原最小环境、无 pyc/cache 断言。
- 补齐前真实失败、补齐后通过；这是 fixture 依赖遗漏，不证明生产发布件已遗漏。
- 隔离中 xcrun 缓存写入曾被拒绝，仍实际进入系统 Python；没有因此扩大全局写权限。

## 证据

- 补齐前：[fix-checks-1mcnt1_u.json](fix-checks-1mcnt1_u.json)，两个模块 exit 1；
  新模板测试的四个 subtest 失败，scheduler helper 缺失；独立 44 项仍通过。
  这说明此前 44/44 不能代替受影响运行入口覆盖。
- 补齐后：[fix-checks-v8ecbs2w.json](fix-checks-v8ecbs2w.json)，84 项执行，82 通过、
  2 项原生 Windows 测试跳过；独立 44/44。所有新旧记录保留。
- 相同拒绝网络、仅任务临时目录可写的隔离 profile；源码、测试和运行器摘要绑定到
  新证据；没有真实服务商请求或全量重复测试。

## 发布与范围审查

- dev 与任务 HEAD 同为 `364ad3076bf29e92d44c06036a520303161b449e`，本地修复尚未提交。
- `stage_plugin.py` 的 Codex 运行时前缀 `scripts/kb/`、Claude 前缀 `scripts/` 均覆盖
  helper，但清单来自 Git 跟踪文件。后续必须一并提交 helper、两个入口与测试。
  本轮没有正式 stage、发布件导入或安装验收，不能拿前缀匹配代替产物证据。
- 已检索其他两个入口的 fixture/部署引用：本次发现的实际源文件最小复制遗漏位于
  scheduler 测试；其他读取范围内的相关 fixture 使用替身脚本，未扩大修改范围。
- 旧报告和运行器保留 pilot 独立评分器依赖，已明确本机任务工具属性；通用单测没有
  pilot 依赖。未来清理 pilot 前需保留所需评分器/样本，不能宣称报告脚本单独可复现。
- 生产配置、正式知识库、调度器、main/dev 未修改；Orca 环境扩建继续暂停。

## 授权与沉淀候选

revision 6 原生 Allow 已应用。首次 Agent 自动决策因跨物理 workspace 路径不满足
资格门而拒绝，随后使用当前会话原生人工卡批准，未改账本绕过规则。宿主再次提示保存
精确 native 命令前缀，调用未请求 prefix_rule；记录为既有独立审计线索，不复用。

候选（verified，本地源码/反例，不直接入库）：失败输出清理需覆盖异常对象链和最小
部署依赖，而非只检查字符串或主目录导入。

- 路由正例：入口引入共享模块，或异常用 from None 抑制显示后被其他消费者接收。
- 路由反例：只需业务成功正文处理，不应据此脱敏或改写合法成功输出。
- 执行正例：合成秘密异常 context/cause 断言，加真实最小系统 Python 启动正反例。
- 执行反例：标准 traceback 没显示秘密就宣称对象链无秘密，或源码目录可导入就宣称
  所有独立部署目录包含新模块。
