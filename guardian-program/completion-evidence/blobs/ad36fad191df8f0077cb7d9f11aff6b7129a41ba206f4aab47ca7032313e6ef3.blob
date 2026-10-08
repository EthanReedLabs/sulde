# T00 — 独立复审记录

## 复审方式

- 审查者只读代码和测试，在临时目录构造状态与失败注入；未修改工作区。
- worker/实现者的成功消息不作为验收依据；每轮发现先登记为 finding，再由 coordinator 修复，
  下一轮复审使用新的文件 SHA。

## 复审轮次

1. 初始复审发现重复 resolution 毒化日志、bogus evidence、completion 竞态、actor 冒充、依赖
   绕过、空转 transfer、初始化尾损坏、superseded 与布尔 schema 等问题。
2. 第二轮发现 current-head unsupported 事件、artifact TOCTOU、多级 successor、pass/fail
   矛盾、replacement 单调性、finding obligation 与 reopen authority 问题。
3. completion 专项复审发现 snapshot 同 UID 改写、orphan snapshot 不可恢复、attested digest
   不一致、hardlink 与 readonly publish 崩溃窗口。
4. 状态不变量复核发现路径别名、竞争 successor、替换依赖 stranded、finding channel union、
   duplicate acceptance，以及 verification run 未参与 gate。
5. 最终两轮所有权对抗发现大小写/Unicode 等价路径，以及任意 glob 规范化和交集判断漏洞；
   控制面最终收紧为精确路径或末尾 `/**` 子树，并重新执行完整矩阵。

## 当前结果

- 控制面全套：56/56 PASS。
- 独立五组状态不变量：10/10 PASS。
- 最终候选 SHA：
  - `guardian_program.py`: `5e710be0a8dd5cb4d9b514035c01f8d056e834a37859c7eee244be3ed442c09e`
  - `test_guardian_program.py`: `f41b69c292687f3733419b4bcc552b73d67c8c87d8d4912994533ac26c837c30`
- 最终候选复审：Blocker 0、High 0，T00 可验收。
