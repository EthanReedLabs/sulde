# 开发与构建

[English](DEVELOPMENT.md) | **简体中文**

本文面向维护者和宿主集成开发者。用户入口见[项目首页](../README.zh-CN.md)。

## 环境与发布件

从已完整提交、无本机数据的干净源码 checkout 构建独立插件包，输出目录必须是新目录：

```sh
python3 -B scripts/release/stage_plugin.py --target claude --output ../sulde-claude-candidate
python3 -B scripts/release/stage_plugin.py --target codex --platform posix --output ../sulde-codex-candidate
python3 -B scripts/release/stage_plugin.py --target codex --platform windows --output ../sulde-codex-windows-candidate
```

构建包含许可文件与宿主所需运行代码。Codex 的裸 `integrations/codex/plugins/sulde`
目录用于适配器开发，正式接入应使用完整 staged 包。

创建输出前，打包器要求 `LICENSE_FILES` 中所有许可和通知文件已被 Git 跟踪、实际存在，
且为非空普通文件。清单包含当前许可证、版权声明、贡献条款、双语许可指南及
[第三方清单](../THIRD_PARTY_NOTICES.zh-CN.md)。Claude 包在根目录携带这些文件；
Codex 包在插件根目录和 runtime 根目录分别携带。历史许可文本通过许可指南中的
固定 Git 链接查阅。

每个发布候选应记录干净源码提交（`git rev-parse HEAD`）、目标平台和最终压缩包的
SHA-256，将压缩包、校验值、源码版本和验证结果一同保存。校验值用于标识字节内容，
不是可信发布时间戳或法律结论。插件版本号不能单独标识许可切换。

Hook 依赖见 `hooks/requirements.txt`。KB 初始化脚本声明 `fastembed`、`jieba`、
`cryptography` 和 `pyyaml`；数值计算与模型依赖由 FastEmbed 提供，没有单独的 KB
requirements 文件。测试时使用独立数据根，不连接已有生产数据目录。

Codex 安装入口为 `scripts/release/install_codex_plugin.py`，通过 `--codex` 选择实际
可执行文件，并绑定绝对路径、版本、文件摘要和协议观察。当前源码审计的 CLI 协议版本为
`codex-cli 0.154.0`；变更可执行文件需重新完成安装验证。受管任务不会通过 PATH 或
`SULDE_CODEX_EXE` 重选 CLI，也不会静默把 v1 部署身份升级为 v2。

真实 CLI 回归检查需要显式设置 `SULDE_TEST_CODEX_EXECUTABLE` 的绝对路径。
缺少该输入的检查记为未验证；该测试参数不能选择生产任务的执行器。

打包检查不替代宿主安装、原生权限确认、Hook 执行和调度器的现场验收。
Windows 包构建成功不等于 Windows 运行验证通过。

`tests/test_control_composition_architecture.py` 和
`tests/test_control_composition_performance.py` 中的历史基线用例依赖私有提交或报告，
不属于可直接在公开仓库运行的通用回归检查；缺失输入时不能报告通过，也不能为运行它们
导入私有历史。SELF 模板不携带操作者目标、历史批准或已经验证的本机能力状态。


## 本地检查

```sh
python3 -B scripts/sulde.py doctor --strict
git diff --check
```

修改后运行受影响模块的回归检查。打包变更还需从干净源码副本验证实际产物，
检查许可文件、入口和运行依赖完整。贡献要求见[贡献指南](../CONTRIBUTING.md)。

## 扩展兼容宿主

Sulde 暴露多种接入接口。`tools/kb-mcp/server.py` 实现 stdio JSON-RPC 初始化、工具发现
和工具调用；项目工具箱通过 `scripts/sulde.py` 暴露 CLI 命令。实现匹配接口的工具可以
复用这些能力。

完整宿主接入还需映射生命周期事件、人的权限决策和受管执行。以
`scripts/kb/host_capabilities.py` 为能力契约，以现有适配器作为具体示例。当前提供方
选择器和打包目标接受 `claude`、`codex`；其他提供方需要显式补齐适配、注册和打包支持。

先验证所选接口，再按需要验证会话身份、工具与结果关联、权限决策和进程完成状态。
区分入口已打包、合成适配检查和真实宿主观察，只声明目标环境中实际验证过的能力。
[现有宿主契约](dual-runtime-contract.md)记录了已提供的 Claude Code、Codex 适配器
及其共享核心边界。
