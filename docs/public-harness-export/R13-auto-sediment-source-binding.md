# R13：auto-sediment 源码仓绑定修复

日期：2026-09-13。承接 [R12-F01](R12-acceptance.md#r12-f01安装包被当成-git-源码仓)。
基线：本地 dev `2170a2a1dcb4f1afff0a443797a80615f853130e`。
范围由当前协调合同 revision 195 的原生 Allow 确认；限本地源码修复、合成测试、报告和 dev 合并。

## 冻结范围与验收状态

- 修复项仅为安装运行时与 Git 知识编辑仓的路径混用，不新增守卫治理或调度架构任务。
- 代码范围：auto-sediment、它调用的五个校验/目录脚本、KB build 入口；加一份测试和本报告，共九个文件。
- 源码级验收已通过；不将其写成生产后台已恢复。
- 未修改 main、其他任务工作区、生产候选/知识/账本、插件 cache、scheduler 或用户 `.ua` 文件；未安装或推送。

## 根因与实施

原入口以 `__file__` 定位 `REPO_ROOT`，在检查待处理候选之前创建 Git worktree。
正式 runtime 没有 `.git`，因此 job 退出 2。单改 launchd WorkingDirectory 无效，因为
子命令指定了 cwd；单改父进程也不够，校验和目录构建脚本各自再次从 `__file__` 取根。

现在分离两个根：

- `RUNTIME_ROOT`：代码、Skill、模板和校验 schema，只使用本次运行时版本。
- `REPO_ROOT`：明确绑定的知识编辑仓；写入流程只在其临时 worktree 中运行。

子进程重用同一运行时脚本，不执行源码仓中的旧脚本；向校验/目录/索引构建入口传递
`--repo-root`。捕获源码 HEAD 后以该 commit 创建 detached worktree，保留既有审查分支、
候选标记、锁、错误恢复和重复 apply 拒绝行为，不自动合并知识审查分支。

源码绑定优先级：显式 `--source-root` → KB home 配置 → 当前脚本自身确为 Git checkout
时的兼容默认。不会从调用方 cwd、其他宿主目录或已安装 owner 的 `source_root` 字段猜测。
最后一项旧字段仍代表发布 runtime，不改其含义。

持久配置文件为 `SULDE_KB_HOME/auto-sediment-source.json`，格式示例：

```json
{
  "schema": "sulde-auto-sediment-source-v1",
  "source_root": "/absolute/knowledge-authoring-checkout",
  "git_common_dir": "/absolute/knowledge-authoring-repository/.git"
}
```

此配置不是授权回执。它必须由获准的部署/配置流程写入，并绑定长期保留的源码 checkout，
不能绑定本任务即将清理的 worktree。`source_root` 与 Git common-dir 必须核实；源码仓
checkout 可以有脏文件，但实际审查分支以其已提交 HEAD 为基线，不携带未提交修改。

缺少绑定、格式错误、非绝对路径、目录丢失、子目录冒充仓库根、common-dir 不匹配、
知识目录 symlink 或环境 Git 路径覆盖均在业务状态写入前失败。不用
`SULDE_AUTO_SEDIMENT_ISOLATED=1` 跳过源仓验证；不符合临时 worktree 结构时拒绝。

## 测试与限制

运行以下 scoped 套件；所有数据来自临时合成仓库，不读取真实候选，不调用模型或安装流程：

```sh
python3 -m unittest tests.test_auto_sediment tests.test_lint_sedimentation \
  tests.test_sedimentation_schema tests.test_corpus_manifest \
  tests.test_kb_index_common tests.test_kb_index_entry \
  tests.test_command_template_split tests.test_scheduler_entrypoints \
  tests.test_export_public_harness -q
```

- Python 3.14.6：88 项，87 通过，1 项 Windows 专用 subprocess 测试在 macOS 按平台跳过。
- auto-sediment 专项 22/22，零跳过（原 15 项 + 新 7 项）。
- 无 `.git` runtime 完成合成 new → lint → catalogs → build → review commit → marker。
  故意把源仓六个脚本替换为失败桩、schema 替换为空对象并提交，仍成功：证明未混用旧代码/规则。
- 安装目录前后逐文件字节一致；源仓 HEAD、脏文件和状态不变；仅审查分支的 knowledge 路径变化，临时 worktree 清理完成。
- 缺失/错误绑定不创建 launch lock、run 文件、候选变更或 Git worktree。
- decide-only → apply 成功；相同 run 再 apply 拒绝，审查分支 HEAD 不变。
- 注入 KB build 失败后，候选内容和调用方源码 checkout 保持原状，无临时 worktree 残留。
- 真实 build.py 入口使用空合成源码仓、带文档的安装包副本和禁止模型初始化的依赖桩：
  输出 docs=0，SQLite `meta.git_head` 对应源码 HEAD，安装包不变。该测试验证选根和真实
  SQLite 写入，不宣称验证了 embedding 模型质量/下载或生产索引健康。
- `git diff --check` 通过；这不是全仓 release-level 验收，不允许直接据此合入 main。

首次开发测试暴露了模板展示标签仍对数据根做 `relative_to` 的遗漏，已统一改为 runtime 根。
新增 SQLite 证据读取的连接也显式关闭。未隐藏失败或削弱原断言来换取通过。

额外执行生产调度器的 `/usr/bin/python3`（3.9.6）：广域 88 项有 1 个既有测试错误、
1 个平台跳过；错误是 `test_kb_index_common.test_manifest_hash_drives_document_hash_and_fingerprint`
的 fixture 使用 3.9 不支持的 `Path.write_text(newline=...)`，并非产品入口异常。
在未修改的 dev 基线独立重跑该单项，同样失败。未修改其测试文件、未把这次运行算作通过，
也未以此扩大九文件范围。生产解释器的 auto-sediment 专项另行执行：22/22 通过，
零跳过，12.009 秒。最终 Python 3.14.6 广域复跑：88 项、87 通过、1 平台跳过，21.933 秒。

## 下一验收边界

本地 dev 集成后，仍须通过官方候选/安装链发布本修复，并经明确部署范围配置长期源码仓绑定。
然后验证已安装入口、job 的新退出结果和 scheduler 分域状态；不能只看 loaded 数量或
interactive ready。未执行该阶段之前，R12 的生产后台阻塞状态保持未关闭。
真实候选的 LLM 调用、标记和知识审查分支产生均须纳入后续 live 卡，不能用空候选测试替代。

## 沉淀候选（Layer1，未直接入库）

- 问题类型：bug-fix / regression；目标：让已安装后台任务具备可执行的知识审查路径。
- 用户预期：不止源码测试通过，安装后实际链路也能运行；不扩大原任务。
- 触发：不带 Git 元数据的正式制品启动会创建审查分支的后台脚本。
- 症状：job exit 2；`cannot locate git common directory`。根因：代码根与写入数据根混用。
- 已排除：只调 cwd 即可修复；源码仓测试通过即可证明安装包路径可用。
- 证据状态：根因与源码修复 verified；新版本生产部署/live 仍未验证。
- 一手证据：R12 安装证据、当前 diff、以上独立合成子进程/SQLite/Git 断言。
- 路由正例：无 Git 制品启动 Git-writing 工具 → apply；必要条件吻合，来源 observed。
- 路由反例：工具只读制品内文档，不生成 Git 审查分支 → skip；不需要编辑仓，来源 constructed。
- 执行合格例：运行时代码固定，绑定源仓的临时分支完成候选流程且安装目录不变 → pass；满足边界，来源 constructed（实际执行测试）。
- 执行失败例：只修主进程 cwd，校验器仍向安装根写目录 → fail；根目录链路不完整，来源 constructed。
- 上浮时泛化项目路径/版本/提交；可复用内核为“不可变运行时与显式编辑仓分离，安装形态做端到端验证”。
- 建议容器：anti-patterns；消费者：发布验收 checklist、Git-writing 后台工具和安装包集成测试。
