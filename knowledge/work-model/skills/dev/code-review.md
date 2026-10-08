---
doc_id: "work-model/skills/dev/code-review"
container: work-model
platform: none
summary: "启动一个 2 人审查团队，分别从架构合规和代码质量两个维度审查指定分支。"
name: code-review
description: 启动代码审查团队，2 个队友从不同维度审查指定分支的代码
user-invocable: true
---

# 代码审查团队

启动一个 2 人审查团队，分别从架构合规和代码质量两个维度审查指定分支。

## 启动方式

用户输入 `/code-review` 后，询问用户需要审查哪个分支。

## 执行步骤

1. 读取 team-config.json 获取项目信息、目录结构、文档路径
2. 确认要审查的分支名
3. 创建 2 人审查团队，审查该分支相对于 dev 的所有改动
4. 审查完成后汇总报告，写入 {directories.reviews} 目录

## 队友分工

**队友 1：架构合规审查**
- 是否遵循 {project.architecture_rule}
- 模块依赖方向是否正确
- 分支提交者身份是否与 CLAUDE.md 映射一致
- 代码中是否存在 AI / Claude / generated 等字样
- 非源码文件是否泄漏到源码目录
- commit message 是否为中文

**队友 2：代码质量和性能审查**
- 内存管理和资源释放
- 并发安全
- 错误处理
- 性能相关决策是否遵循性能文档

## 队友 spawn prompt 模板

```
你是 {project.name} 项目的代码审查员。

项目源码位置：当前工作目录（pwd）
项目目录结构：{directories.source}

审查目标：{分支名} 相对于 {branches.dev} 的所有改动

获取改动范围的命令：
git diff {branches.dev}...{分支名} --stat
git diff {branches.dev}...{分支名}
git log {branches.dev}..{分支名} --oneline
git log {branches.dev}..{分支名} --format="%an <%ae> %s"

你的审查维度是：{架构合规 / 代码质量和性能}

审查标准参考：
- 项目规则：{references.project_rules}
- 架构规范：{references.architecture}
- 平台设计：{references.platform_design}
- 性能决策：{references.performance}

输出格式：
1. 列出发现的问题，按严重程度排序（阻断 / 需修复 / 建议优化）
2. 每个问题标注文件路径和行号
3. 给出修复建议
4. 不要自动修改代码，只输出审查报告
5. 报告写入 {directories.reviews}/{分支名}-{日期}.md
```
