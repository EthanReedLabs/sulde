from __future__ import annotations

from contextlib import contextmanager
import json
import io
import os
import re
import runpy
import signal
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PLUGIN_ROOT / "runtime"


@contextmanager
def _execution_deadline(timeout: float, command: list[str]):
    """Preserve the former subprocess timeout for POSIX in-process Hooks."""
    if os.name == "nt" or not hasattr(signal, "setitimer"):
        yield
        return
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def expired(_signum, _frame):
        raise subprocess.TimeoutExpired(command, timeout)

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


def configure_utf8_stdio() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


def normalize_codex_session(payload: dict[str, Any]) -> dict[str, Any]:
    """Give every Codex Hook phase the same durable native session identity.

    Some Codex payload versions omit ``sessionId`` outside SessionStart while
    still exporting ``CODEX_THREAD_ID``.  Letting those phases fall back to an
    empty/workspace lane is what allowed two sessions in one checkout to share
    task state.  The environment value is a host identity hint only; contract
    routing remains owned by the persisted session-workspace mapping.
    """
    if not str(payload.get("session_id") or "").strip():
        selected = str(
            payload.get("sessionId") or os.environ.get("CODEX_THREAD_ID") or ""
        ).strip()
        if selected:
            payload["session_id"] = selected
    return payload


def runtime_root() -> Path:
    # 发布件形态:stage_plugin 把运行时拷进 plugin/runtime(自包含);
    # 开发机形态:无 staging,回退到仓库根(integrations/codex/plugins/sulde → 仓库),
    # 保持"改码即生效"
    if RUNTIME_ROOT.is_dir():
        return RUNTIME_ROOT
    configured = os.environ.get("SULDE_SOURCE_ROOT")
    if configured:
        candidate = Path(configured).expanduser()
        if (candidate / "scripts" / "kb").is_dir():
            return candidate
    # 本地 marketplace 会把裸 plugin 复制进 ~/.codex/plugins/cache，缓存内没有
    # staging 生成的 runtime/，也已失去相对仓库位置。此时从 Codex 配置中已登记的
    # local marketplace source 反查源码根；只接受同时含 scripts/kb 与 CANON.md 的祖先。
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    try:
        config = (codex_home / "config.toml").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        config = ""
    for match in re.finditer(
        r"(?ms)^\[marketplaces\.[^\]]+\]\s*$\n(.*?)(?=^\[|\Z)", config
    ):
        block = match.group(1)
        if not re.search(r'(?m)^source_type\s*=\s*["\']local["\']\s*$', block):
            continue
        source_match = re.search(r'(?m)^source\s*=\s*("(?:[^"\\]|\\.)*")\s*$', block)
        if not source_match:
            continue
        try:
            source = Path(json.loads(source_match.group(1))).expanduser().resolve()
        except (TypeError, ValueError, OSError, json.JSONDecodeError):
            continue
        for candidate in (source, *list(source.parents)[:6]):
            if (candidate / "scripts" / "kb").is_dir() and (candidate / "CANON.md").is_file():
                return candidate
    repo_root = PLUGIN_ROOT.parents[3]
    if (repo_root / "scripts" / "kb").is_dir():
        return repo_root
    return RUNTIME_ROOT


def run_runtime(
    script: Path,
    *,
    args: tuple[str, ...] = (),
    input_text: str | None = None,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    if os.environ.get("SULDE_CODEX_IN_PROCESS_HOOK") == "1":
        old_argv = sys.argv
        old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
        stdin_bytes = io.BytesIO((input_text or "").encode("utf-8"))
        stdout_bytes = io.BytesIO()
        stderr_bytes = io.BytesIO()
        sys.stdin = io.TextIOWrapper(stdin_bytes, encoding="utf-8", errors="strict")
        sys.stdout = io.TextIOWrapper(stdout_bytes, encoding="utf-8", errors="strict")
        sys.stderr = io.TextIOWrapper(stderr_bytes, encoding="utf-8", errors="replace")
        sys.argv = [str(script), *args]
        command = [sys.executable, "-B", str(script), *args]
        returncode = 0
        try:
            with _execution_deadline(timeout, command):
                runpy.run_path(str(script), run_name="__main__")
        except SystemExit as error:
            returncode = error.code if isinstance(error.code, int) else (0 if error.code is None else 1)
        except subprocess.TimeoutExpired:
            raise
        except BaseException:  # match a child Python process without killing the bridge
            traceback.print_exc(file=sys.stderr)
            returncode = 1
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            stdout = stdout_bytes.getvalue().decode("utf-8", errors="replace")
            stderr = stderr_bytes.getvalue().decode("utf-8", errors="replace")
            sys.argv = old_argv
            sys.stdin, sys.stdout, sys.stderr = old_stdin, old_stdout, old_stderr
        return subprocess.CompletedProcess(
            command,
            returncode,
            stdout,
            stderr,
        )
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-B", str(script), *args],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=timeout,
        check=False,
    )
