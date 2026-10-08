---
doc_id: "work-model/skills/dev/bug-hunt"
container: work-model
platform: none
summary: "启动一个 3 人排查团队，从不同角度调查问题，互相讨论找出最可能的原因。"
name: bug-hunt
description: 启动 Bug 排查团队，3 个队友从不同角度排查问题并互相讨论找出根因
user-invocable: true
---

# Bug 排查团队

启动一个 3 人排查团队，从不同角度调查问题，互相讨论找出最可能的原因。

## 启动方式

用户输入 `/bug-hunt` 后，依次询问：

1. Bug 的具体表现是什么？
2. 复现条件和出现频率？
3. 在哪个分支上出现的？（默认 {branches.dev}）
4. 有没有 crash log / 堆栈信息 / 错误日志？（可选）

## 执行步骤

1. 读取 team-config.json 获取项目信息、目录结构、文档路径、日志命令
2. 收集 Bug 信息（表现 + 复现条件 + 分支 + 日志）
3. 根据 Bug 特征制定 3 个排查方向
4. 创建 3 人团队，每人负责一个方向
5. 队友之间互相讨论，挑战对方的假设
6. 汇总结论，给出最可能的根因和修复方案
7. 评估修复方案是否会引入新问题

## 队友分工原则

根据 Bug 特征动态分配排查方向。常见的排查维度：

- 生命周期 / 状态管理
- 内存 / 资源管理
- 线程 / 并发安全
- 网络 / 数据流
- UI 渲染 / 布局
- 平台兼容性 / 版本差异

## 队友 spawn prompt 模板

```
你是 {project.name} 项目的 Bug 排查工程师。

Bug 描述：{Bug 表现}
复现条件：{复现步骤}
出现频率：{频率}
所在分支：{分支名}
日志信息：{crash log / 堆栈 / 错误日志，如有}

你的排查方向是：{排查维度}

项目源码位置：当前工作目录（pwd）
请先 checkout 到 {分支名} 分支，再开始排查。

项目目录结构：{directories.source}

日志获取方式：
（从 team-config.json 的 log_commands.{platform} 读取对应平台的全部日志命令）

排查步骤：
1. 如果用户没有提供日志，主动使用上述命令获取日志
2. 根据你的排查方向，定位可能相关的代码文件并阅读源码
3. 分析代码逻辑，结合日志找出可能导致该 Bug 的原因
4. 提出你的假设和证据
5. 主动和其他队友讨论，挑战对方的假设，也接受对方对你的挑战
6. 最终给出你的结论

参考文档：
- 项目规则：{references.project_rules}
- 架构规范：{references.architecture}
- 平台设计：{references.platform_design}
- 性能决策：{references.performance}

输出格式：
1. 假设：你认为 Bug 的原因是什么
2. 证据：支持你假设的代码位置和逻辑（标注文件路径和行号）
3. 反证：不支持你假设的证据
4. 置信度：0-100%
5. 修复方案：具体改哪个文件的哪段代码
6. 修复风险评估：修复是否可能引入新问题，是否符合 {project.architecture_rule}
7. 排查报告写入 {directories.bug_reports}/{Bug简述}-{日期}.md
```
