---
doc_id: "ap-0202"
container: anti-patterns
platform: none
summary: "shell 拼接生成的 JSON 工件肉眼看着正常,下游 json 解析却报非法——多行文本里的换行/转义未按 JSON 规则处理,且生成脚本从未做过合法性校验"
sedimented_by: auto
related: [ap-0205]
---

# NNNN — shell 手写 JSON 换行转义错误且无合法性自测

- **平台**:通用

## ❌ 错误

用 echo / printf / heredoc / 字符串拼接在 shell 里手写 JSON 工件,并把"看起来像 JSON"当作生成成功:

```bash
# 多行内容直接内插:真实换行符进入 JSON 字符串 → 非法 JSON
BODY=$(cat some.log)
echo "{\"msg\": \"$BODY\"}" > artifact.json

# 或 printf/echo -e 把 \n 展开成真实换行;或单引号上下文把 \n 留成字面反斜杠+n
# 两个方向都可能与 JSON 转义规则错位
```

生成后只目测或 grep 检查,不做解析级校验。

## 为什么

JSON 字符串内的换行必须写成转义序列 `\n`,真实换行字符是非法的;而 shell 有自己独立的一层引号/转义语义(双引号内插、`echo -e`、heredoc 引号形态各不相同),两层转义规则叠加后,`\n` 到底落盘成"两个字符的转义序列"还是"真实换行"极难靠肉眼判断。文件看起来结构完整、缩进正常,但一到下游 `json.load` / `JSON.parse` 就报错——错误在消费端才暴露,离生成点远,排查成本高。

## ✅ 正确

1. **生成端不手拼**:JSON 一律用序列化器生成,让工具负责转义——

```bash
# jq:--arg 自动做 JSON 转义
jq -n --arg msg "$BODY" '{msg: $msg}' > artifact.json

# 或 python
python3 -c 'import json,sys; print(json.dumps({"msg": sys.stdin.read()}))' < some.log > artifact.json
```

2. **自测必须是解析级校验**:任何生成 JSON 工件的脚本/流程,验收步骤必须包含真实解析,不以目测为准——

```bash
python3 -m json.tool artifact.json > /dev/null && echo OK
# 或在测试代码里 json.load(open(path)) 能通过才算生成成功
```

校验放在生成侧(而非等下游消费报错),错误暴露点与出错点重合,一步定位。
