---
doc_id: "ap-0237"
container: anti-patterns
platform: cross
summary: "异步 native 推理仍在同步提交阶段时释放 runner，协程取消未等待 JNI/FFI 调用结束，最终形成 use-after-free 崩溃。"
related: [ap-0236]
---

# 0237 — 异步原生推理提交与关闭并发

- **平台**：跨端 / JNI / FFI
- **复发次数**：1

## ❌ 错误

页面退出时先 `job.cancel()`，随后立即 `close()` 原生推理 runner。另一线程可能仍在
`detectAsync`、packet/image 构造或 generation submit 的同步 JNI/FFI 段中。runner 的
native handle 已被释放，提交线程继续使用旧指针，进程以 SIGSEGV/EXC_BAD_ACCESS 终止。

增加 `closed` 布尔值再在提交前检查也不能解决：检查通过到进入 native 之间仍存在
TOCTOU 窗口。

## 为什么错

- 协程取消通常只发出取消信号，不保证正在执行的同步 native 调用已经返回。
- 名为 async 的 SDK 方法，调用端仍可能先同步构造 packet、复制图像或访问 runner 状态。
- runner 关闭与提交属于同一个资源所有权协议，却被两个线程独立执行。
- 不再调用 `close()` 会暂时隐藏崩溃，但会积累 native 内存、线程或 GPU 资源。

## ✅ 正确

1. 由 runner 所有者统一序列化“进入 native 提交”和“关闭 runner”两个临界区。
2. 关闭时先阻止新提交，再等待或排空当前同步提交，最后释放 runner 与输入强引用。
3. 回调、取消、异常和正常完成共用同一幂等 teardown；重复关闭不能再次释放句柄。
4. 若 SDK 提供 cancel-and-join，仍需确认它覆盖同步 JNI/FFI 段，而非只等待上层协程。
5. 高帧率/高并发下反复进入退出，同时验证无 native 崩溃、无线程泄漏和无内存持续增长。

## lint 状态

- ⚠️ 可检：同一 owner 中出现异步 native submit、协程 `cancel()` 和 runner `close()`，但没有
  共享锁、actor 或显式 join 协议。
- ✅ 压测门禁：在提交前、同步 native 段和等待回调期分别注入 teardown。
- ❌ `volatile closed`、捕获 Java/Kotlin/Swift 异常或依赖 GC/finalizer 均不能证明安全。
