---
doc_id: "ap-0179"
container: anti-patterns
platform: ios
summary: "0179 .strings 引号语法错误未用 plutil 校验全部 locale"
---

# 0179 .strings 引号语法错误未用 plutil 校验全部 locale

- **平台**:iOS
- **复发次数**:1

## ❌ 错误

把 `.strings` 当作任意文本编辑，在翻译值中混用 Unicode 智能引号与未转义的 ASCII 双引号：

```text
"example.key" = "Text with „an "unclosed quote";
```

并且只人工检查当前 locale 或当前页面。

## 为什么错

`.strings` 是有语法约束的资源。未转义的 ASCII `"` 会提前闭合字符串，导致资源编译或运行解析失败。单页面验收无法覆盖全部 locale，未被当前语言加载的语法错误也容易长期潜伏。

## ✅ 正确

使用成对的智能引号，或按 `.strings` 语法转义 ASCII 双引号，并对仓库内每个 locale 的每个 `.strings` 文件执行：

```bash
find Sources -path '*.lproj/*.strings' -type f -print0 |
  xargs -0 -n1 plutil -lint
```

将 `plutil -lint` 接入 CI 或 pre-commit，确保任一 locale 解析失败都阻断提交。

## lint 状态

- ✅ `plutil -lint` 可对 `.strings` 语法做确定性校验。
- CI：遍历全部 `.lproj`，不能只校验默认 locale。
- 关联：本地化资源既要检查覆盖率，也要检查每个已有资源的可解析性。
