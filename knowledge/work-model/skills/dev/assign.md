---
doc_id: "work-model/skills/dev/assign"
container: work-model
platform: none
summary: "指派一个任务给指定开发者，自动切换到对应分支和 git 身份。"
name: assign
description: 指派单人任务，自动切换到对应分支和 git 身份执行
user-invocable: true
---

# 任务指派

指派一个任务给指定开发者，自动切换到对应分支和 git 身份。

## 启动方式

用户输入 `/assign` 后，依次询问：

1. 指派给谁？（输入代号 A / B / C 或姓名，从 team-config.json 的 developers 读取映射）
2. 在哪个分支上？（新建 / 已有）
3. 任务描述？

## 执行步骤

1. 读取 team-config.json 获取开发者代号映射
2. 根据代号或姓名确定 git alias 和用户名
3. 切换或创建对应分支
4. 读取 CLAUDE.md 确认规则
5. 执行任务
6. 完成后不要自动提交，等待确认

## 执行模板

```
当前身份：{developer.name}（{developer.alias}）
当前分支：{branches.pattern}
任务内容：{任务描述}

项目源码位置：当前工作目录（pwd）
项目目录结构：{directories.source}

git 操作：
- 新建分支：git checkout {branches.dev} && git checkout -b {branches.pattern}
- 切换分支：git checkout {branches.pattern}
- 提交使用：{developer.alias}

参考文档：
- 项目规则：{references.project_rules}
- 实施文档：{references.implementation}
- 架构规范：{references.architecture}
- 平台设计：{references.platform_design}
- 性能决策：{references.performance}

规则：
1. 所有提交使用 {developer.alias}，commit message 用中文
2. 代码中禁止出现 AI / Claude / generated 等字样
3. 非源码文件放 {directories.workspace}
4. 完成后不要自动提交，等待确认
5. 遵循 {project.architecture_rule}
```
