---
doc_id: "ap-0225"
container: anti-patterns
platform: none
summary: "同一份脚本在开发者终端跑得好好的,换成程序去启动就失败——Windows 上 subprocess 启动无扩展名脚本报 WinError 193、os.execve 触发访问违例、商店别名在受限令牌下拒绝访问,三者都只在非交互场景暴露"
related: ["ap-0183", "ap-0224"]
---

# 0225 — Windows 进程启动的三个坑:无扩展名脚本 / execve / 商店别名

- **平台**:none(Windows 宿主特有,但影响所有跨平台工具链)

## ❌ 错误

跨平台工具链在 POSIX 上验证通过后直接上 Windows,踩到三类互不相同的进程启动失败。
共同点:**都只在"由程序启动"时暴露,人在终端里手敲全都正常**。

### 坑一:把无扩展名脚本当可执行文件传给 subprocess

```python
subprocess.run(["/path/to/mytool", "sub-cmd"])     # mytool 无扩展名,首行是 shebang
# Windows: OSError [WinError 193] %1 不是有效的 Win32 应用程序
```

POSIX 由内核读 shebang 派发解释器;**Windows 的 `CreateProcess` 不认 shebang**,
只认 PE 可执行体与已注册的扩展名。带 `#!/usr/bin/env python3` 的纯文本同样失败——
是不是 Python 内容无关,**没有扩展名就不可直接启动**。

给脚本加 `.py` 也不够:`.py` 能否直接启动取决于宿主的文件关联与 `PATHEXT`,
在裁剪过的环境里通常不成立。

### 坑二:在 Windows 上用 os.execve

```python
os.execve(interpreter, argv, env)   # POSIX 语义:进程替换
# Windows: 稳定触发 0xC0000005 访问违例
```

Windows 无 `exec` 语义,该调用由运行时模拟,在带管道/句柄继承的场景下不可靠。

### 坑三:应用商店别名(App Execution Alias)在受限令牌下不可启动

沙箱/降权场景用受限令牌调 `CreateProcessAsUserW`,若目标解析到商店别名
(位于 `%LOCALAPPDATA%\Microsoft\WindowsApps` 下的重解析点):

```
CreateProcessAsUserW failed: 5 (拒绝访问)
```

别名指向的安装目录 ACL 不接受受限令牌。**`which`/`shutil.which` 会优先返回这个别名**,
于是"依赖找得到"与"依赖能启动"是两回事。

## 为什么

- **三者都属于"交互式能跑 ≠ 程序能起"**。人在终端里由 shell 兜底(shell 读 shebang、
  用完整令牌、有完整 PATH),换成程序直启就没有这层兜底。参见 [[ap-0224]]。
- **失败信息不指向真因**。`WinError 193` 字面是"不是有效的 Win32 应用程序",容易被
  读成"文件坏了";`0xC0000005` 看起来像内存越界;`error 5` 看起来像权限配置问题。
  三条都不会说"你不该这样启动它"。
- **常与静默吞噬叠加**。这类启动失败多发生在后台任务/hook 里,外面往往包着
  `except OSError: pass`,于是缺陷可以存活到某个依赖它的功能大面积失效才被发现。

## ✅ 正确

- **显式指定解释器,不依赖宿主派发**:`[sys.executable, str(script), *args]`,
  或解析出目标虚拟环境的解释器再传。脚本是不是无扩展名就都无所谓了。
- **平台分支处理进程替换**:POSIX 用 `os.execve` 保持原语义,Windows 改用
  `subprocess.run` 并透传退出码。
- **依赖发现要验"能启动",不只验"找得到"**:`which` 命中后再实际拉起一次;
  或在解析结果落到已知的别名目录时跳过它。
- **在最小环境下验收**:显式清空环境,只给 `SYSTEMROOT`/`USERPROFILE`/系统 PATH,
  复现宿主派生子进程的真实条件。
- 若必须保留"单一入口"的稳定路径,**把入口本身改写为可被解释器直接执行的形态**,
  而不是让每个调用方各自绕开它。
