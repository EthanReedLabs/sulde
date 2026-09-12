"""Shared, cross-platform launcher for the Sulde KB CLI."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


_COMMANDS: dict[str, tuple[Path, tuple[str, ...]]] = {
    "build": (Path("tools/kb-index/build.py"), ()),
    "search": (Path("tools/kb-index/search.py"), ()),
    "related": (Path("tools/kb-index/search.py"), ("related",)),
    "fleet": (Path("scripts/kb/fleet.py"), ()),
    "mem-init": (Path("tools/kb-index/memory.py"), ("init",)),
    "mem-embed": (Path("tools/kb-index/memory.py"), ("embed-pending",)),
    "mem-search": (Path("tools/kb-index/memory.py"), ("search",)),
    "mem-annotate": (Path("tools/kb-index/memory.py"), ("annotate",)),
    "mem-graph": (Path("tools/kb-index/memory.py"), ("graph",)),
    "mem-recent": (Path("tools/kb-index/memory.py"), ("recent",)),
    "mem-prune": (Path("tools/kb-index/memory.py"), ("prune",)),
}


def command_names() -> tuple[str, ...]:
    """Return public KB subcommands in their stable display order."""
    return tuple(_COMMANDS)


class CliUnavailableError(RuntimeError):
    """The configured KB runtime cannot construct a command."""


@dataclass(frozen=True)
class CliResult:
    status: str
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class SpawnResult:
    status: str

    @property
    def started(self) -> bool:
        return self.status == "started"


def resolve_venv_python(
    home: Path, *, require_executable: bool = False
) -> Path | None:
    """Return the first supported venv interpreter, optionally requiring execute access."""
    return next(
        (
            candidate
            for candidate in (
                home / "venv" / "bin" / "python",
                home / "venv" / "Scripts" / "python.exe",
            )
            if candidate.is_file()
            and (not require_executable or os.access(candidate, os.X_OK))
        ),
        None,
    )


def build_command(
    root: Path,
    home: Path,
    subcommand: str,
    arguments: Sequence[str] = (),
    *,
    python: Path | None = None,
    entry_root: Path | None = None,
) -> list[str]:
    """Resolve one public KB subcommand to its explicit Python invocation."""
    try:
        entry, prefix = _COMMANDS[subcommand]
    except KeyError as error:
        raise ValueError(f"unknown KB CLI subcommand: {subcommand}") from error
    interpreter = python or resolve_venv_python(home)
    if interpreter is None:
        raise CliUnavailableError(
            f"venv Python not found under {home / 'venv'} "
            "(tried bin/python, Scripts/python.exe)"
        )
    entrypoint = entry_root / entry.name if entry_root is not None else root / entry
    return [
        str(interpreter),
        str(entrypoint),
        *prefix,
        *(str(argument) for argument in arguments),
    ]


def _notify(diagnostic: Callable[[str], None] | None, result: CliResult) -> None:
    if diagnostic is None or result.ok:
        return
    message = f"status={result.status}"
    if result.returncode is not None:
        message += f" exit_code={result.returncode}"
    if result.detail:
        message += f" detail={result.detail}"
    try:
        diagnostic(message)
    except (OSError, ValueError):
        return


def run_cli(
    root: Path,
    home: Path,
    subcommand: str,
    arguments: Sequence[str] = (),
    *,
    timeout: float,
    diagnostic: Callable[[str], None] | None = None,
    stdout=None,
    stderr=None,
) -> CliResult:
    """Run a KB CLI command without allowing launch failures to escape."""
    try:
        command = build_command(root, home, subcommand, arguments)
    except (CliUnavailableError, ValueError) as error:
        result = CliResult("unavailable", detail=str(error))
        _notify(diagnostic, result)
        return result

    capture_output = stdout is None and stderr is None
    try:
        environment = os.environ.copy()
        environment["SULDE_KB_HOME"] = str(home)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            capture_output=capture_output,
            stdout=stdout,
            stderr=stderr,
            text=capture_output,
            encoding="utf-8" if capture_output else None,
            errors="replace" if capture_output else None,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        result = CliResult("timeout", detail=f"timeout after {error.timeout}s")
    except (OSError, ValueError) as error:
        result = CliResult(
            "launch_failed",
            detail=f"{type(error).__name__}: {error}",
        )
    else:
        result = CliResult(
            "ok" if completed.returncode == 0 else "nonzero_exit",
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            detail=(completed.stderr or "").strip()[-500:],
        )
    _notify(diagnostic, result)
    return result


def _append_diagnostic(log_path: Path, subcommand: str, result: CliResult) -> None:
    message = f"[sulde-kb-cli] command={subcommand} status={result.status}"
    if result.returncode is not None:
        message += f" exit_code={result.returncode}"
    if result.detail:
        message += f" detail={result.detail}"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as stream:
            stream.write((message + "\n").encode("utf-8", errors="replace"))
    except OSError:
        try:
            sys.stderr.write(message + "\n")
        except (OSError, ValueError):
            return


def spawn_cli(
    root: Path,
    home: Path,
    subcommand: str,
    arguments: Sequence[str] = (),
    *,
    timeout: float,
    log_path: Path,
) -> SpawnResult:
    """Start a detached, timeout-bounded CLI supervisor using the venv Python."""
    try:
        python = resolve_venv_python(home)
        if python is None:
            raise CliUnavailableError(
                f"venv Python not found under {home / 'venv'} "
                "(tried bin/python, Scripts/python.exe)"
            )
        if subcommand not in _COMMANDS:
            raise ValueError(f"unknown KB CLI subcommand: {subcommand}")
        command = [
            str(python),
            str(Path(__file__).resolve()),
            "__supervise__",
            str(root),
            str(home),
            str(log_path),
            str(timeout),
            subcommand,
            *(str(argument) for argument in arguments),
        ]
        subprocess.Popen(
            command,
            cwd=root,
            env={
                **os.environ,
                "SULDE_KB_HOME": str(home),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        return SpawnResult("started")
    except (CliUnavailableError, OSError, ValueError) as error:
        result = CliResult(
            "unavailable" if isinstance(error, CliUnavailableError) else "launch_failed",
            detail=f"{type(error).__name__}: {error}",
        )
        _append_diagnostic(log_path, subcommand, result)
        return SpawnResult(result.status)


def _supervise(arguments: Sequence[str]) -> int:
    if len(arguments) < 5:
        return 2
    root = Path(arguments[0])
    home = Path(arguments[1])
    log_path = Path(arguments[2])
    try:
        timeout = float(arguments[3])
    except ValueError:
        return 2
    subcommand = arguments[4]
    cli_arguments = arguments[5:]
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as stream:
            result = run_cli(
                root,
                home,
                subcommand,
                cli_arguments,
                timeout=timeout,
                stdout=stream,
                stderr=subprocess.STDOUT,
            )
    except OSError as error:
        result = CliResult(
            "log_unavailable",
            detail=f"{type(error).__name__}: {error}",
        )
    _append_diagnostic(log_path, subcommand, result)
    return result.returncode or (0 if result.ok else 1)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "__supervise__":
        raise SystemExit(_supervise(sys.argv[2:]))
    raise SystemExit(2)
