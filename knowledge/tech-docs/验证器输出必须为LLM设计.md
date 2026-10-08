---
doc_id: tech-docs/验证器输出必须为LLM设计
container: tech-docs
platform: none
summary: 测试/验证脚本把成千上万行原始日志整段灌回 agent 上下文,一次验证吃掉大半窗口且关键错误被淹没
related: []
---

# 验证器输出必须为 LLM 设计

## 原则

agent 要消费的验证输出,按四条设计:

1. **摘要进上下文**:一行结论(PASS/FAIL)+ 计数(passed/failed)+ 失败项**名字**
2. **细节进文件**:完整日志写到带时间戳的 artifact 文件,只把**路径**给 agent
3. **错误行可 grep**:失败细节带统一前缀(ERROR/FAIL),agent 需要什么自己
   `grep ERROR <日志路径>` 按需读取
4. **统计预计算**:计数、耗时、差值由脚本算好,不让 agent 从原始输出里数

```
VERIFY RESULT: FAIL
failed: 2  passed: 148
ERROR audio_switch_test
ERROR reconnect_timeout_test
details: .artifacts/test/20260807-103213.log
```

## 为什么

- agent 的智能 × 验证反馈质量 = 实际可用能力——反馈是乘数,不是加数
- 原始构建日志动辄数万行:整段回灌一次就污染大半上下文窗口,后续轮次
  推理质量全面下降;而其中 agent 真正需要的通常只有失败项名和一两段错误栈
- "按需 grep"把读取决策还给 agent:它知道自己缺什么,比脚本猜"该给多少"准

## 适用面

不止测试:构建输出、部署日志、批量校验、数据迁移报告——一切"agent 将读取
其结果并据此行动"的脚本输出,都按此四条设计。人看的详细报告继续存在,
只是活在 artifact 文件里而非上下文里。
