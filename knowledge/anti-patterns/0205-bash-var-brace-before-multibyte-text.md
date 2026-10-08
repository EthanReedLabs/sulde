---
doc_id: "ap-0205"
container: anti-patterns
platform: none
summary: "同一脚本 bash 5 正常、bash 3.2(如 macOS 自带 /bin/bash)报 unbound variable 或展开为空——变量展开后紧跟中文等多字节字符未加花括号,旧版 bash 把多字节字符的字节吞进变量名"
related: [ap-0202]
sedimented_by: auto
---

# NNNN — shell 变量后紧跟多字节字符必须加花括号 ${var}

- **平台**:通用(跨 bash 版本脚本)

## ❌ 错误

变量展开后直接紧跟中文(或其他多字节字符),不加花括号:

```bash
set -u
count=3
echo "共 $count条记录"   # bash 5 正常输出;bash 3.2 报 unbound variable
```

在新版 bash 上跑通就当作写法正确,不在目标平台的旧版 bash 上验证。

## 为什么

变量名的边界由 shell 解析器判定:解析器在扫描 `$name` 时会一直吃合法标识符字符,遇到非标识符字符才停。新版 bash(如 bash 5)按多字节字符正确断词,中文字符被识别为非标识符字符,变量名在此结束;而旧版 bash(如 macOS 系统自带的 bash 3.2)按字节处理,多字节字符的部分字节可能被当作标识符字符吞进变量名,实际查找的是一个不存在的变量——`set -u` 下直接报 unbound variable,不开 `-u` 则静默展开为空,错误更隐蔽。

同一脚本两个平台行为相反(双向实证),且失败发生在"看起来完全正常"的写法上:开发机(新 bash)全绿,目标机(旧 bash)才炸,排查时很难第一时间怀疑到变量名断词。

## ✅ 正确

1. **变量后紧跟任何非 ASCII 文本时一律写 `${var}`**:

```bash
echo "共 ${count}条记录"   # 花括号显式划定变量名边界,任何 bash 版本行为一致
```

2. **跨平台脚本的通用纪律**:目标环境含旧版 bash(尤其 macOS 默认 /bin/bash 3.2)时,变量展开与相邻文本拼接一律加花括号,不依赖解析器断词;
3. **验证要覆盖最老的目标 bash**:在支持矩阵里最老的 bash 版本上真实跑一遍(如 `bash --version` 确认 3.2),不以新版跑通为准;配合 `set -u` 让吞名错误在测试期就显式暴露,而不是静默展开为空。
