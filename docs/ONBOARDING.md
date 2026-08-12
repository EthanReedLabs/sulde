# sulde-cc Community 0.3.0 接入指南

本指南面向新项目、老项目、内网项目和维护公开 fork 的团队。公开版的定位是“骨架与
方法”，接入方负责补全自己的规则、知识和扩展，不依赖私有 Sulde 仓库。

## 0. 先确认边界

公开版提供 Claude Code 插件骨架、确定性 hook、移动端模板、扩展生成器和空知识容器。
它不提供项目语料、用户记忆、MCP 服务、向量检索、后台 Agent、L2/L3/L4 治理或自治执行。

如果目标是接入公开版，验收标准是：从干净安装件运行 `sulde doctor`、项目显式 opt-in、
完成一次 task → verify → handoff 闭环。不能把另一宿主或私有仓库当作隐式依赖。

## 1. 环境契约

- Claude Code（支持 plugin）
- Python 3.10+
- PyYAML 6.0+
- Git
- macOS/Linux：POSIX shell
- Windows：Claude Code hook 使用 Git Bash 或 WSL2；手动 CLI 可使用 `scripts/sulde.ps1`

```sh
python3 --version
python3 -m pip install -r hooks/requirements.txt
./scripts/sulde doctor --strict
```

## 2. 安装方式

### GitHub marketplace

```text
/plugin marketplace add EthanReedLabs/sulde-cc
/plugin install sulde-cc@sulde-cc
```

### 本地 fork

```sh
git clone https://github.com/EthanReedLabs/sulde-cc.git
cd sulde-cc
python3 -m pip install -r hooks/requirements.txt
./scripts/sulde doctor
```

把该目录加入 Claude Code marketplace 后安装。更新 fork 后应重新执行干净安装诊断，不能
只凭源码目录里的测试判断已安装产物可用。

### 内网或气隙

联网侧从 Git 跟踪文件制作归档；内网侧解压后先运行 `sulde doctor`。不要携带 `.git`、
缓存、`__pycache__`、会话日志或本机配置。归档必须保留 Git 中记录的脚本执行位。

## 3. 新项目

在项目根运行 `/sulde-init`，按实际项目填写：

- role：`coordinator` / `dev` / `both`
- frontends：真实目录与 stack
- docs_hub：真实文档根
- design_source：真实工具或 `none`
- enforcement_level 与 grace period
- team 与 Git alias（单人项目可留空）
- primary OS

生成后运行：

```sh
"${CLAUDE_PLUGIN_ROOT}/scripts/sulde" doctor --project "$PWD"
"${CLAUDE_PLUGIN_ROOT}/scripts/sulde" kb lint --root "$PWD"
```

模板里出现的名称、路径和命令都是待接入方验证的骨架，不代表项目现状。

## 4. 老项目

老项目坚持三条原则：显式 opt-in、不移动业务源码、不覆盖已有治理设施。

1. 先审计已有 `.claude/`、`CLAUDE.md`、Git hook、文档根和 monorepo 子目录。
2. 让 `.sulde-config.yaml.frontends[].path` 映射现有目录。
3. 已有 Git hook 时使用链式调用或现有 hook manager 集成，不直接替换。
4. 已有 `CLAUDE.md` 时追加 Sulde 边界段，不整文件覆盖。
5. 用 `sulde kb init --root .` 只补缺失的知识骨架；已有文件一律保留。
6. 在 grace period 内完成一条真实任务，再切到目标 enforcement level。

## 5. 项目自定义扩展

扩展生成器用于 fork，不用于把私有内容复制进公开仓库：

```sh
./scripts/sulde add-skill verify-release --description "验证发版证据"
./scripts/sulde add-hook scope-gate --event PreToolUse --matcher "Write|Edit"
./scripts/sulde add-check toolchain-ready
./scripts/sulde add-knowledge-container domain-notes
```

生成器只创建新文件并登记一次，遇到重名或已有路径就失败。生成后的 hook/skill 仍需人工
review 和测试，它们不会自动获得写文件、联网、发布、提交或推送权限。

## 6. 项目知识成长

知识真值位于接入项目自己的 `knowledge/*.md`。最小闭环：

1. 用症状描述执行 `kb dedup`。
2. 对原始事故材料执行 `kb redact`，输出到新文件；原文不被改写。
3. 执行 `kb sediment` 创建 `status: draft` 的脱敏草稿。
4. 人工补齐根因、通用修法和验证证据。
5. 执行 `kb lint` 与 `kb index`。
6. review 后再由项目自己的 Git 流程提交。

这个闭环不调用模型、服务或 MCP，也不自动把草稿变为 active。

## 7. 多人团队

- 每个 frontend 记录 owner 或 team alias。
- task-md 是范围和验收契约，handoff 是证据载体。
- 协调端不能凭印象填写项目类名、路径、token 或工具状态；写入前先在仓库验证。
- 同一纠正维度重复出现时，先修订任务契约再继续，避免把矛盾指令堆进上下文。

## 8. 升级与回退

升级前：

```sh
git status --short
./scripts/sulde doctor --json
python3 -m unittest discover -s tests -v
```

升级后从新的安装件再跑一次 doctor。公开版不自动迁移接入方扩展；对
`extensions/registry.json`、自定义 skill/hook/check 与知识 schema 做显式 diff。

需要回退时切回已知版本并重新安装 plugin。不要只改 `VERSION` 或只替换一个 hook 文件，
否则会形成混合版本运行时。
