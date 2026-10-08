# LLM 失败诊断：dev 交付与打包验收

2026-09-23。状态：代码已提交并快进合入 dev；本地 Codex POSIX 产物验证通过。
没有 push、cachebuster、正式安装、真实模型调用或 Orca 扩建。

## 代码与测试绑定

- 修复提交：`898906ac30814dc14d4d5c4735504d8e0acfc191`。
- 合入前 dev：`364ad3076bf29e92d44c06036a520303161b449e`。
- main 保持 `43be088f0f1234573af5a4c8bfe90df6f0d5aea2`。
- 定向测试：82 通过、2 项原生 Windows 跳过；独立合成检查 44/44。
  打包验收器先回读 `fix-checks-v8ecbs2w.json` 的全部源码/测试/运行器摘要，
  与已提交 dev 文件逐项一致才复用结果，没有重复全量测试。
- 本报告及产物验收工具/证据属于后续 docs-only 提交，不改变被测产品代码。
  产物绑定上面的精确代码提交，不伪称在后来任意 HEAD 上重新执行过发布验收。

## 实际产物证据

[artifact-checks-ovxc_ayd.json](artifact-checks-ovxc_ayd.json) 记录每一步退出码、
输出摘要、源 commit、generation、目标文件哈希和独立检查明细。

1. 使用仓库 `stage_plugin.py --target codex --platform posix` 实际打包，exit 0。
   打包器执行 corpus/history 校验、宿主产物校验及 generation 密封后复核。
2. 两个入口及新增 `llm_diagnostics.py` 均在 artifact 中，逐字节摘要等于 dev。
3. 管理的 Python 及 `/usr/bin/python3` 各启动两个 artifact 入口的 `--help`，
   4/4 exit 0；环境没有继承宿主 PATH、生产 HOME 或生产数据根。
4. 新进程从 artifact/runtime 加载两个入口，真实 fake-LLM 子进程与独立矩阵
   44/44 通过。未运行真实模型，也不是完整 annotation/backfill 的生产验收。
5. 验证前后 runtime tree 摘要完全相同，无 pyc、__pycache__ 或符号链接。

runtime tree SHA-256：
`cc7bbfa9b9b696c81bdd1af8cfdea050f430c3733e7a5f6ef4d7ec95d84b6c79`。

产物仍沿用源码 manifest 版本 `0.2.5+codex.20260923070231-1c75e2322a`；
这是本地验证产物，不是新安装版本。不得因版本号与已安装值相同而认为生产已升级。
私有产物位于暂停 pilot 的 `.pilot-runtime/artifact-checks-ovxc_ayd/codex`，未上传。

## 环境与已知边界

- `artifact-offline.sb` 拒绝网络及任务临时根以外的写入。为了真实 Git staging，
  只读开放当前 Git common-dir；git 配置使用私有 HOME，不读取用户凭证。
- 系统 Python 的 xcrun 缓存写入仍受隔离限制；帮助入口实际执行成功，不因缓存
  警告扩大权限。stage/帮助调用的 stderr 非空不等于失败，完整原始输出不入报告。
- 本机验收工具仍依赖保留的 pilot 评分器与 fixture，不是独立可搬移的通用 CI。
- Windows 原生执行、正式安装与实际服务商故障链未在本轮验证。
- 生产 generation、配置、调度器、知识库和记忆未修改。

## 授权与资源收尾

Guardian revision 7 原生 Allow 批准本地提交、dev 合入、产物检查与已合并临时资源
收尾。三个技能用于限定任务范围、保留宿主配置和核验受限运行环境（KB ap-0224）。

当前会话合同的物理 workspace 已在 dev，doctor 的 workspace_cleanup 为 not_applicable；
它不是待删除任务目录的合同。不得把 dev 当作 release 的可删除源工作区，也不得为
制造清理回执而篡改合同。任务 worktree/分支仅在最终证据提交、完全合入、工作树干净
后由普通 Git 做精确清理；报告与补丁保留在 dev，暂停的 pilot 和其他任务不在删除范围。

## 沉淀候选

verified：新增共享模块要用已跟踪源码打包，并从产物目录启动；源码目录的绿测不证明
运行件包含它。路由正例：新增运行时 import/runpy 依赖；路由反例：仅任务报告变动。
执行正例：source/artifact 摘要一致、受限新进程启动和业务正反例、运行后树不变；
执行反例：只看前缀清单或沿用旧安装版本号就宣称新产物/生产可用。未写入正式知识库。
