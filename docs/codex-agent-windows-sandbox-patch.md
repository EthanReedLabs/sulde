# codex-agent 技能：Windows 沙箱补丁记录

> 本文档是**本机外文件的补丁记录**。被修改的文件位于 `~/.claude/skills/codex-agent/scripts/launch.sh`，
> 该目录不是 git 仓库，修复无版本管理。换机、重装技能或技能自身更新覆盖后，修复会静默丢失。
> 届时按本文重新应用。
>
> 记录日期：2026-08-07 ｜ 环境：Windows 11、Git Bash、codex-cli 0.146.1

## 症状

在原生 Windows 上通过 `scripts/launch.sh` 发起的**任何**后台 codex 委托全部空转：codex 连一个子进程都启动不了，五次工具调用后按熔断规则停止，汇报"任务完全未落地"。

危险之处在于**失败伪装成拒绝**：

- `codex exec` 退出码 **0**
- `<slug>.status` 写入 `status=success`
- 只有 `.last.md` 正文里说没干成

也就是说，仅凭状态文件判定完成的自动化流程会把彻底失败误判为成功。实际是靠 `verify.sh` 判 FAIL、`git diff` 为空才截获。

## 根因

codex 的 Windows 沙箱用 `CreateProcessAsUserW` + **受限令牌**启动 shell。它选中的是 PATH 上第一个 `pwsh`，在本机解析为：

```
C:\Users\spiel\AppData\Local\Microsoft\WindowsApps\pwsh.exe
```

这是微软商店的 **App Execution Alias**——一个指向 `C:\Program Files\WindowsApps\Microsoft.PowerShell_7.6.4.0_x64__8wekyb3d8bbwe\pwsh.exe` 的重解析点。该目录的 ACL 不接受受限令牌，于是每条沙箱命令都失败：

```
windows sandbox: runner failed during SpawnChild:
CreateProcessAsUserW failed: 5 (拒绝访问。)
| cwd=D:\GitHub\sulde-cc-pro
| cmd=C:\Users\spiel\AppData\Local\Microsoft\WindowsApps\pwsh.exe -NoProfile -Command "..."
```

注意 `cwd` 解析完全正确——**这不是路径问题**。首次诊断曾误判为 MSYS 路径转换问题，是靠读 stderr 原文推翻的。

## 复现与验证

两次对照，均在 Git Bash 下、使用原生 Windows cwd，以排除路径变量：

| 条件 | 结果 |
|---|---|
| 原样执行 | `CreateProcessAsUserW failed: 5` |
| 仅将 `WindowsApps` 移出 PATH | `git version 2.51.1.windows.1` |

摘掉别名目录后，codex 回落到 `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`——普通文件，受限令牌可正常启动。

**代价评估**：该目录下仅有商店应用别名（ASUS 套件、Xbox、截图工具、`winget` server、WSL 的 `bash.exe` 别名等）。`python` / `python3` / `pytest` 均另有真实路径且在 PATH 中更靠前，不受影响。

## 补丁

`~/.claude/skills/codex-agent/scripts/launch.sh`，插入在 `START=$(date +%s)` 之前、`ARGS=(...)` 之后：

```sh
# Windows only: codex's sandbox spawns its shell through CreateProcessAsUserW with
# a restricted token. When `pwsh` resolves to the Microsoft Store App Execution
# Alias under %LOCALAPPDATA%\Microsoft\WindowsApps, that reparse point into
# Program Files\WindowsApps denies the restricted token and EVERY sandboxed
# command dies with "CreateProcessAsUserW failed: 5" — codex then exits 0 while
# reporting the task as impossible, so the failure reads like a refusal, not a
# crash. Dropping the alias dir from PATH for this invocation only lets codex
# fall back to System32 powershell.exe. Reproduced + verified 2026-08-07 on
# codex-cli 0.146.1; no-op on macOS/Linux and when the fallback is unavailable.
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*)
    STRIPPED_PATH=$(printf '%s' "$PATH" | tr ':' '\n' | grep -viE '/WindowsApps/?$' | paste -sd: -)
    if PATH="$STRIPPED_PATH" command -v powershell >/dev/null 2>&1; then
      PATH="$STRIPPED_PATH"; export PATH
    fi
    unset STRIPPED_PATH
    ;;
esac
```

设计要点：

- 只在 MSYS/MinGW/Cygwin 下生效，macOS/Linux 完全空操作
- 只在确认 `powershell` 摘除后仍可解析时才替换，否则保持原样——宁可不修，不制造更坏的 PATH
- 只影响本次 `codex exec` 调用，不改用户 shell 环境

## 验证方法

打补丁后跑一次只读冒烟：

```sh
bash ~/.claude/skills/codex-agent/scripts/launch.sh <某目录> smoke read-only <brief文件>
cat <某目录>/.codex-agent/smoke.status     # 应为 status=success
cat <某目录>/.codex-agent/smoke.last.md    # 应含命令的真实输出，而非"无法执行"
```

关键在于**看 `.last.md` 正文有无真实命令输出**，而不只是看 `.status` 是否 success——本缺陷的整个危险性就在于 status 会骗人。

## 备选通道

若补丁不便应用（例如技能被上游覆盖），改走 **codex MCP 同步通道**（`mcp__codex__codex` / `codex-reply`）并传原生 Windows cwd。实测该通道不触发本缺陷。代价是同步阻塞、且不能用 `verify.sh` 的发射前快照做范围核对，需改用 `git diff --stat` 人工核对改动范围。
