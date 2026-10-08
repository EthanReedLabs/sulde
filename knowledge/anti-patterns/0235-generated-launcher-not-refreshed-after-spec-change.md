---
doc_id: "ap-0235"
container: anti-patterns
platform: cross
summary: "跨平台 launcher 的规范或目标形态已经从 shell 改为 Python，但其他机器上 bootstrap 生成的旧包装器不会随 Git 更新自动重建，最终由旧壳解释新目标并在对端失败"
related: [ap-0183, ap-0225, tech-docs/派生产物缓存双失效与负缓存]
sedimented_by: auto
---

# 0235 — launcher 规范已更新，但已生成包装器仍是旧壳

- **平台**：macOS / Linux / Windows 跨平台工具链
- **复发次数**：1

## ❌ 错误

仓库把入口从 shell 改为 Python，并同步修改 launcher spec；本机源码测试通过后只推 Git，
却没有让其他机器重跑 bootstrap。对端的 `$KB_HOME/bin/...` 仍是旧 shell 包装器，随后把
新的 Python 文件交给 `bash`，出现 `from: command not found` 等看似源码损坏的错误。

另一个常见假绿是：测试统一 mock `subprocess.run`，但 POSIX 生产分支实际走
`os.execve`，测试在 macOS/Linux 根本没有经过所断言的调用。

## 为什么

- launcher spec 是生成规则，已安装包装器是派生产物；更新前者不会远程改写后者。
- 入口形态变化跨越了解释器边界，旧包装器不是“版本略旧”，而是会用错误语言解析目标。
- Windows 与 POSIX 为保持进程语义通常走不同分支；只在一端运行一套无平台守卫的测试，
  不能证明另一分支，也可能在当前平台断言一条永远不会执行的路径。

## ✅ 正确

1. spec 变更时提升 launcher/cachebuster 版本，并在安装态记录 `spec_version` 与目标摘要；
   启动时不匹配就明确要求重跑 bootstrap，禁止继续猜解释器。
2. 交付说明与自动同步提示必须列出所有已安装消费者；源码拉取完成不等于运行时已同步。
3. bootstrap 后做真实 installed-artifact smoke：检查 shebang/解释器、调用最小子命令，并
   验证包装器引用的是当前仓库目标。
4. 同一函数的 Windows `subprocess.run` 与 POSIX `os.execve` 分支各有用例；平台集成测试
   使用互斥 `skipIf/skipUnless`，共享语义抽到纯函数做全平台单测。不能在 POSIX 上断言
   Windows 调用路径，反之亦然。
5. CI 至少包含 Windows 与 POSIX 两个 job，并保存生成后的 launcher 作为验收工件。

## lint 状态

- ✅ 可检：spec/入口形态变更时，cachebuster/bootstrap fixture 与双平台测试必须同批更新。
- ✅ 安装态门禁：`spec_version` 或目标摘要不匹配时 fail closed。
- ❌ 仅验证仓库源码无法证明另一台机器的已生成包装器已刷新。
