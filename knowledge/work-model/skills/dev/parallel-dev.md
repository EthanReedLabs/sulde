---
doc_id: "work-model/skills/dev/parallel-dev"
container: work-model
platform: none
summary: "启动一个多人开发团队，每个队友在独立的 worktree 中工作，互不冲突。"
name: parallel-dev
description: 启动并行开发团队，多个队友在各自 worktree 中并行开发不同模块
user-invocable: true
---

# 并行开发团队

启动一个多人开发团队，每个队友在独立的 worktree 中工作，互不冲突。

## 开发者代号

读取 team-config.json 中的 developers 配置，获取代号→姓名→alias→领域的映射。用户可以用代号（A/B/C）或姓名指定队友。

## 启动方式

用户输入 `/parallel-dev` 后，询问用户需要并行开发哪些模块，以及各模块分配给谁（A/B/C）。

## 执行步骤

1. 读取 team-config.json 获取开发者信息、分支命名规则、项目目录结构
2. 根据用户指定的模块和代号，确定每个队友的分支名和对应的 git alias
3. 创建团队，每个队友的 spawn prompt 必须包含：
   - 所在分支名和对应的 git alias
   - 使用 worktree 隔离
   - 项目源码位置和目录结构（从 team-config.json 的 directories 读取）
   - 技术文档路径（从 team-config.json 的 references 读取）
   - 遵循 CLAUDE.md 的全部规则
   - 完成后不要自动提交，等待确认

## 队友 spawn prompt 模板

```
你是 {project.name} 项目的开发者 {developer.name}（{developer.alias}）。
你的任务是在 {branches.pattern} 分支上实现 {模块描述}。

项目源码位置：当前工作目录（pwd）
项目目录结构：{directories.source}

创建分支命令：
git checkout {branches.dev}
git checkout -b {branches.pattern}

技术方案参考：
- 项目规则：{references.project_rules}
- 实施文档：{references.implementation}
- 架构规范：{references.architecture}
- 平台设计：{references.platform_design}
- 性能决策：{references.performance}

规则：
1. 从 {branches.dev} 分支创建 {branches.pattern}
2. 所有提交使用 {developer.alias}，commit message 用中文
3. 代码中禁止出现 AI / Claude / generated 等字样
4. 非源码文件放 {directories.workspace}
5. 完成后不要自动提交，等待确认
6. 遵循 {project.architecture_rule}
```

## 示例

用户输入：`/parallel-dev`
助手询问：需要并行开发哪些模块？分配给谁？
用户回答：A 做模块甲，C 做基础设施，B 做模块乙

助手读取 team-config.json，启动团队：
- 队友 A → {branches.pattern} → 实现模块甲
- 队友 C → {branches.pattern} → 实现基础设施
- 队友 B → {branches.pattern} → 实现模块乙
