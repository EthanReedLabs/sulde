---
doc_id: "ap-0204"
container: anti-patterns
platform: none
summary: "shell 断言用 grep/rg 匹配含 *、.、[ 等字符的字面字符串,元字符被当正则解释——断言变宽出现假阳性(测试照样绿),或匹配不到预期内容,错误远离出错点才暴露"
related: [ap-0203]
sedimented_by: auto
---

# NNNN — grep 断言中字面量含正则元字符被当作模式解释

- **平台**:none

## ❌ 错误

在 shell 脚本/测试断言里,用默认模式的 `grep` / `rg` 去匹配一个**本意是字面字符串**、但含有 `*`、`.`、`[`、`+`、`?` 等字符的内容:

```bash
# 断言输出里含字面 "foo.*" 这段文本
echo "$output" | grep 'foo.*'        # ❌ .* 被解释为"任意字符",几乎匹配一切

# 断言配置行 "pattern: *.log" 存在
grep 'pattern: *.log' config.txt     # ❌ " *"=零或多个空格,.=任意字符,语义完全走样
```

断言写完只看"绿了",不验证它在反例输入下会不会误绿。

## 为什么

- grep 默认按正则(BRE)解释 pattern,rg 默认按正则解释;`.` `*` `[` 等在字面量里极常见,却都是元字符
- 错配方向多为**假阳性**:`.` 匹配任意单字符、`x*` 允许零次出现,断言比本意更宽——测试照常通过,坏变更静默放行,问题在离断言很远的下游才暴露
- 也可能假阴性(如 `[` 开启字符类导致 pattern 非法或匹配不到),两个方向都不易靠肉眼从 pattern 文本看出

## ✅ 正确

- 断言字面字符串一律加 `-F`(fixed-strings,grep/rg 通用),让工具按逐字符比较处理:

```bash
echo "$output" | grep -F 'foo.*'
grep -F 'pattern: *.log' config.txt
```

- 确实需要正则时,显式转义字面部分的元字符,或改用 `-F` + 多次匹配组合表达
- 自检/review 判据:凡 shell 断言中 grep/rg 的 pattern 含 `.` `*` `[` 等字符,先问"意图是正则还是字面";是字面就必须有 `-F`
- 对关键断言做一次反例自测:喂入一个不该匹配的输入,确认断言真的会红

## lint

可半机械化:扫描脚本中 grep/rg 调用点,pattern 含正则元字符且无 `-F`/`--fixed-strings` 的,标出人工确认意图。
