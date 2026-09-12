---
name: sulde-add-sensitive-file
description: 将敏感文件同时登记到 Sulde advisory 配置和项目级 Claude harness deny，且保留既有 settings。用于 /sulde-add-sensitive-file、维护 scope_sensitivity.sensitive_files 或为项目敏感路径添加 Edit/Write deny。
---

# /sulde-add-sensitive-file — 敏感文件双保险登记

Args: `<path>`，路径必须相对项目根（例：`core-ui/AppRouter.kt`）。本流程把同一路径登记到两层：`.sulde-config.yaml` 提供 advisory/self-fix 边界，项目 `.claude/settings.json` 的 `permissions.deny` 提供 harness 级拒绝。

## 1. 执行

从插件根运行确定性实现：

```bash
python3 skills/sulde-add-sensitive-file/scripts/register.py '<path>'
```

脚本从 cwd 向上定位最近的 `.sulde-config.yaml` 并完成下列两层合并。找不到配置时提示先运行 `/sulde-init`。只接受非空的项目相对路径；拒绝绝对路径、`..` 越界和项目根本身；统一使用 `/` 分隔，不要求目标文件已经存在。脚本失败时停止，不得手工补做一半后宣称成功。

## 2. 更新 Sulde advisory 配置

向 `.sulde-config.yaml` 的 `scope_sensitivity.sensitive_files` 去重追加规范化相对路径。保留所有其他配置字段；若 `scope_sensitivity` 或 `sensitive_files` 不存在则创建对应 mapping/list。

## 3. 合并项目 harness deny

目标是 `<project-root>/.claude/settings.json`。用 JSON 结构化读写完成以下操作：

1. 文件不存在时从空对象开始；存在时必须解析为 JSON object，否则停止并报告，不能覆盖。
2. 若原文件存在且 `<project-root>/.claude/settings.json.bak-sulde` 尚不存在，写入变更前先用 `shutil.copy2` 创建该首次备份；已有备份绝不覆盖。新建 settings 时不创建空备份。
3. 保留所有其他键和值。确保 `permissions` 是 object、`permissions.deny` 是 array；类型冲突时停止并报告。
4. 按现有顺序去重追加这两条精确规则：

   ```text
   Edit(<相对路径>)
   Write(<相对路径>)
   ```

5. 创建 `.claude/`（如缺失），以 UTF-8、两空格缩进和末尾换行写回。优先先写同目录临时文件再 `os.replace`，减少半写文件风险。

重复登记必须幂等：YAML 路径与 deny 两条规则都只出现一次。

## 4. 验证与输出

脚本会重新读取并验证两个文件。向用户复述脚本结果，说明双保险语义、两个落点和备份是否新建，并提醒：Dev 自发修改仍受 self-fix-boundary 限制，正式改动须经 task md。
