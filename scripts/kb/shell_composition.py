"""Bounded, non-executing plans for literal foreground shell compositions.

This is deliberately not a shell interpreter. The original shell still owns
short-circuiting, pipeline concurrency and exit status. A plan lists *possible*
steps, never claims they ran, and is not an authorization receipt.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import shlex
from command_template import split_command_template


class CompositionError(ValueError):
    pass


@dataclass(frozen=True)
class ShellStep:
    command: str
    after: str
    redirects: tuple[tuple[str, str], ...] = ()


def literal_shell_plan(command: str) -> tuple[ShellStep, ...]:
    """Parse literal argv, |, &&, ||, ;, newlines and file redirections.

    Expansion, background jobs and shell-state changes cannot borrow a static
    plan. Quoted operators remain data. Bounds are independent of log size.
    """
    if len(command) > 65536 or "\0" in command:
        raise CompositionError("命令超出静态分析边界")
    tokens: list[tuple[str, str]] = []
    word: list[str] = []
    quote = ""
    index = 0

    def flush() -> None:
        if word:
            raw = "".join(word)
            try:
                values = split_command_template(raw, os_name="posix")
            except ValueError as error:
                raise CompositionError("参数引号不完整") from error
            if len(values) != 1:
                raise CompositionError("参数不能静态解析")
            tokens.append(("word", values[0]))
            word.clear()

    while index < len(command):
        char = command[index]
        if char == "\\" and quote != "'":
            if index + 1 == len(command):
                raise CompositionError("转义不完整")
            if command[index + 1] == "\n":
                index += 2
                continue
            word.extend(command[index:index + 2])
            index += 2
            continue
        if quote:
            if quote == '"' and char in "$`":
                raise CompositionError("参数包含动态展开，无法确定实际动作或目标")
            word.append(char)
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in "\"'":
            quote = char
            word.append(char)
        elif char == "#" and not word:
            end = command.find("\n", index)
            index = len(command) if end < 0 else end
            continue
        elif char in "\n\r":
            flush()
            # Shell accepts blank lines, including after && and pipes.
            if tokens and tokens[-1][0] not in {"operator"}:
                tokens.append(("operator", ";"))
        elif char.isspace():
            flush()
        elif char in "|&;":
            flush()
            operator = char
            if command[index:index + 2] in {"&&", "||"}:
                operator = command[index:index + 2]
                index += 1
            elif char == "&" or command[index:index + 2] in {"|&", ";;", ";&"}:
                raise CompositionError("后台或扩展 shell 控制流无法静态绑定")
            tokens.append(("operator", operator))
        elif char in "<>":
            descriptor = ""
            if word and "".join(word).isdigit():
                descriptor = "".join(word)
                word.clear()
            flush()
            operator = char
            if command[index:index + 2] == ">>":
                operator = ">>"
                index += 1
            elif command[index:index + 2] in {">&", "<&"}:
                operator = command[index:index + 2]
                index += 1
            elif command[index:index + 2] in {"<<", "<>", ">|"}:
                raise CompositionError("该重定向需要明确的文件或描述符目标")
            tokens.append(("redirect", descriptor + operator))
        elif char in "$`(){}[]*?~!" or (char == "=" and not word):
            raise CompositionError("包含动态展开、分组或模式目标，不能证明实际步骤")
        else:
            word.append(char)
        index += 1
    if quote:
        raise CompositionError("参数引号不完整")
    flush()

    steps: list[ShellStep] = []
    argv: list[str] = []
    redirects: list[tuple[str, str]] = []
    after = "start"
    index = 0

    def step() -> None:
        if not argv:
            raise CompositionError("组合包含空命令")
        if argv[0] in {
            "cd", "eval", "exec", "export", "source", ".", "set", "unset",
            "alias", "unalias", "function", "if", "while", "for", "case",
            "command", "builtin", "env", "xargs",
        } or re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", argv[0]):
            raise CompositionError("步骤改变执行上下文或动态选择程序；请明确 workdir 和可执行程序")
        steps.append(ShellStep(shlex.join(argv), after, tuple(redirects)))
        if len(steps) > 64:
            raise CompositionError("组合超过 64 个步骤")
        argv.clear()
        redirects.clear()

    while index < len(tokens):
        kind, value = tokens[index]
        if kind == "word":
            argv.append(value)
        elif kind == "redirect":
            if index + 1 >= len(tokens) or tokens[index + 1][0] != "word":
                raise CompositionError("重定向缺少明确目标")
            index += 1
            if "&" in value and (tokens[index][1] not in {"0", "1", "2", "-"} or value.rstrip("<>&") not in {"", "0", "1", "2"}):
                raise CompositionError("只能绑定已知的标准输入输出描述符")
            redirects.append((value, tokens[index][1]))
        else:
            step()
            after = value
        index += 1
    if argv:
        step()
    elif redirects or after not in {"start", ";"}:
        raise CompositionError("组合末尾缺少命令")
    return tuple(steps)
