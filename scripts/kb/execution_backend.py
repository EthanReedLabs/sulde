"""Provider-neutral process execution seam for managed Sulde L3 runs.

The backend owns process publication and teardown.  A provider result and
resource cleanup are separate terminal facts: partial output never converts a
non-completed stop reason into success, and a successful provider result is not
publishable until the process tree is quiescent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Mapping, Sequence, TextIO
import uuid


RUN_EVENT_SCHEMA = "sulde-run-event-v1"
RUN_STOP_REASONS = frozenset(
    {
        "completed",
        "error",
        "aborted",
        "timeout",
        "policy_paused",
        "awaiting_human",
    }
)


class ExecutionBackendError(RuntimeError):
    """A run cannot be published, settled, or cleaned up safely."""


@dataclass(frozen=True)
class RunResult:
    run_id: str
    returncode: int
    stop_reason: str
    output_present: bool
    output_sha256: str | None

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and self.stop_reason == "completed"


@dataclass(frozen=True)
class CleanupResult:
    run_id: str
    quiescent: bool
    idempotent: bool
    tree_scope: str
    errors: tuple[str, ...]


@dataclass(frozen=True)
class RunLedgerProjection:
    run_id: str
    provider: str
    requested: bool
    started: bool
    start_failed: bool
    interrupted: bool
    result: dict[str, Any] | None
    disposed: dict[str, Any] | None
    recovery_blocked: bool
    pid: int | None
    tree_scope: str
    terminal: bool
    publishable: bool
    rows: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _workspace_identifier(path: Path) -> str:
    return "sha256:" + hashlib.sha256(
        str(path.resolve()).encode("utf-8", errors="replace")
    ).hexdigest()[:24]


def _append_event(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        written = os.write(descriptor, encoded)
        if written != len(encoded):
            raise OSError("run event append was partial")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_run_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = path.read_bytes()
        text = payload.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise ExecutionBackendError(f"run ledger cannot be read: {error}") from error
    if payload and not payload.endswith(b"\n"):
        raise ExecutionBackendError(
            "run ledger has an incomplete tail; preserve it for human recovery"
        )
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            raise ExecutionBackendError(
                f"run ledger contains a blank row at line {line_number}"
            )
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ExecutionBackendError(
                f"run ledger contains invalid JSON at line {line_number}: {error}"
            ) from error
        if not isinstance(value, dict):
            raise ExecutionBackendError(
                f"run ledger row {line_number} is not an object"
            )
        rows.append(value)
    return rows


def replay_run_ledger(path: Path) -> RunLedgerProjection | None:
    """Validate one run's append-only lifecycle without trusting summary files."""
    rows = _read_run_rows(path)
    if not rows:
        return None
    run_id = str(rows[0].get("run_id") or "")
    provider = str(rows[0].get("provider") or "unknown")
    if not re.fullmatch(r"run-[0-9a-f]{24}", run_id):
        raise ExecutionBackendError("run ledger has an invalid run id")
    requested = False
    started = False
    start_failed = False
    interrupted = False
    result: dict[str, Any] | None = None
    disposed: dict[str, Any] | None = None
    recovery_blocked = False
    pid: int | None = None
    tree_scope = "unknown"
    for line_number, row in enumerate(rows, 1):
        if row.get("schema") != RUN_EVENT_SCHEMA:
            raise ExecutionBackendError(
                f"run ledger row {line_number} has an unsupported schema"
            )
        if row.get("run_id") != run_id:
            raise ExecutionBackendError("run ledger mixes multiple run ids")
        if str(row.get("provider") or "unknown") != provider:
            raise ExecutionBackendError("run ledger changes provider within one run")
        if not isinstance(row.get("at"), str) or not row["at"].strip():
            raise ExecutionBackendError(
                f"run ledger row {line_number} has no timestamp"
            )
        event_type = str(row.get("type") or "")
        if event_type == "execution.requested":
            if line_number != 1 or requested:
                raise ExecutionBackendError("execution.requested must be the first event")
            requested = True
        elif event_type == "execution.started":
            if not requested or started or start_failed or result is not None:
                raise ExecutionBackendError("execution.started is out of order")
            try:
                pid = int(row.get("pid"))
            except (TypeError, ValueError) as error:
                raise ExecutionBackendError("execution.started pid is invalid") from error
            if pid < 1:
                raise ExecutionBackendError("execution.started pid must be positive")
            tree_scope = str(row.get("tree_scope") or "unknown")
            started = True
        elif event_type == "execution.start_failed":
            if not requested or started or start_failed or result is not None:
                raise ExecutionBackendError("execution.start_failed is out of order")
            start_failed = True
        elif event_type == "execution.interrupt_requested":
            if not started or start_failed or result is not None:
                raise ExecutionBackendError(
                    "execution.interrupt_requested is out of order"
                )
            if interrupted:
                raise ExecutionBackendError(
                    "execution.interrupt_requested is duplicated"
                )
            interrupted = True
        elif event_type == "execution.recovery_blocked":
            if not requested or start_failed or result is not None:
                raise ExecutionBackendError("execution.recovery_blocked is out of order")
            recovery_blocked = True
        elif event_type == "execution.result":
            if not requested or start_failed or result is not None:
                raise ExecutionBackendError("execution.result is out of order or duplicated")
            try:
                returncode = int(row.get("returncode"))
            except (TypeError, ValueError) as error:
                raise ExecutionBackendError("execution.result returncode is invalid") from error
            stop_reason = str(row.get("stop_reason") or "")
            if stop_reason not in RUN_STOP_REASONS:
                raise ExecutionBackendError("execution.result stop reason is invalid")
            result = {**row, "returncode": returncode}
        elif event_type == "execution.disposed":
            if result is None or disposed is not None:
                raise ExecutionBackendError("execution.disposed is out of order or duplicated")
            if not isinstance(row.get("quiescent"), bool):
                raise ExecutionBackendError("execution.disposed quiescence is invalid")
            try:
                error_count = int(row.get("error_count"))
            except (TypeError, ValueError) as error:
                raise ExecutionBackendError(
                    "execution.disposed error count is invalid"
                ) from error
            if error_count < 0:
                raise ExecutionBackendError(
                    "execution.disposed error count must be non-negative"
                )
            disposed = {**row, "error_count": error_count}
        else:
            raise ExecutionBackendError(
                f"run ledger row {line_number} has unsupported type {event_type!r}"
            )
        if (start_failed or disposed is not None) and line_number != len(rows):
            raise ExecutionBackendError("run ledger has events after a terminal fact")
    terminal = start_failed or disposed is not None
    publishable = bool(
        result is not None
        and result["returncode"] == 0
        and result.get("stop_reason") == "completed"
        and disposed is not None
        and disposed.get("quiescent") is True
        and disposed.get("error_count") == 0
    )
    return RunLedgerProjection(
        run_id=run_id,
        provider=provider,
        requested=requested,
        started=started,
        start_failed=start_failed,
        interrupted=interrupted,
        result=result,
        disposed=disposed,
        recovery_blocked=recovery_blocked,
        pid=pid,
        tree_scope=tree_scope,
        terminal=terminal,
        publishable=publishable,
        rows=len(rows),
    )


def _process_group_exists(pid: int) -> bool:
    if os.name == "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def recover_incomplete_run(
    path: Path,
    *,
    settle_timeout: float = 1.5,
) -> RunLedgerProjection | None:
    """Close a hard-crash prefix only when process-tree absence is provable."""
    projection = replay_run_ledger(path)
    if projection is None or projection.terminal:
        return projection
    tree_absent = False
    tree_scope = projection.tree_scope
    if projection.started and projection.pid is not None:
        deadline = time.monotonic() + max(0.0, settle_timeout)
        while _process_group_exists(projection.pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        tree_absent = not _process_group_exists(projection.pid)
    elif projection.requested:
        first = _read_run_rows(path)[0]
        if first.get("parent_death_watchdog") is True:
            time.sleep(min(max(settle_timeout, 0.0), 0.6))
            tree_absent = True
            tree_scope = "posix-parent-death-watchdog"
    if not tree_absent:
        if not projection.recovery_blocked:
            _append_event(
                path,
                _event(
                    projection.run_id,
                    "execution.recovery_blocked",
                    provider=projection.provider,
                    reason_code="process_tree_still_observable",
                    process_identity="unknown",
                ),
            )
        return replay_run_ledger(path)
    if projection.result is None:
        _append_event(
            path,
            _event(
                projection.run_id,
                "execution.result",
                provider=projection.provider,
                returncode=255,
                stop_reason="aborted",
                output_present=False,
                output_sha256=None,
                recovered_from_crash=True,
            ),
        )
    _append_event(
        path,
        _event(
            projection.run_id,
            "execution.disposed",
            provider=projection.provider,
            quiescent=True,
            tree_scope=tree_scope or "recovered-process-tree",
            error_count=0,
            errors_sha256=None,
            recovered_from_crash=True,
        ),
    )
    return replay_run_ledger(path)


def _event(run_id: str, event_type: str, **values: Any) -> dict[str, Any]:
    return {
        "schema": RUN_EVENT_SCHEMA,
        "at": _now(),
        "run_id": run_id,
        "type": event_type,
        **values,
    }


def _windows_job_for(process: subprocess.Popen[str]) -> int | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class BASIC_LIMITS(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED_LIMITS(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMITS),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None
        limits = EXTENDED_LIMITS()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        configured = kernel32.SetInformationJobObject(
            handle,
            9,  # JobObjectExtendedLimitInformation
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        )
        process_handle = wintypes.HANDLE(int(process._handle))  # type: ignore[attr-defined]
        assigned = configured and kernel32.AssignProcessToJobObject(handle, process_handle)
        if not assigned:
            kernel32.CloseHandle(handle)
            return None
        return int(handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _close_windows_handle(handle: int) -> bool:
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        return bool(kernel32.CloseHandle(wintypes.HANDLE(handle)))
    except (AttributeError, OSError, TypeError, ValueError):
        return False


class RunHandle:
    """One published process run with one result and idempotent disposal."""

    def __init__(
        self,
        *,
        run_id: str,
        process: subprocess.Popen[str],
        ledger_path: Path,
        provider: str,
        windows_job: int | None,
        watchdog_fd: int | None,
        cleanup_grace: float,
    ) -> None:
        self.id = run_id
        self.process = process
        self.ledger_path = ledger_path
        self.provider = provider
        self._windows_job = windows_job
        self._watchdog_fd = watchdog_fd
        self._cleanup_grace = cleanup_grace
        self._result: RunResult | None = None
        self._cleanup: CleanupResult | None = None
        self._interrupt_reason: str | None = None
        self._lock = threading.RLock()

    @property
    def result(self) -> RunResult | None:
        return self._result

    @property
    def cleanup(self) -> CleanupResult | None:
        return self._cleanup

    def _group_exists(self) -> bool:
        if os.name == "nt":
            return self.process.poll() is None
        try:
            os.killpg(self.process.pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def _wait_group_gone(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while self._group_exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        return not self._group_exists()

    def _terminate_tree(self) -> tuple[bool, str, list[str]]:
        errors: list[str] = []
        if os.name == "nt":
            if self._windows_job is not None:
                handle = self._windows_job
                self._windows_job = None
                closed = _close_windows_handle(handle)
                if not closed:
                    errors.append("CloseHandle(job) failed")
                try:
                    self.process.wait(timeout=self._cleanup_grace)
                except subprocess.TimeoutExpired:
                    errors.append("job close did not settle leader")
                return closed and self.process.poll() is not None, "windows-job", errors
            if self.process.poll() is None:
                try:
                    completed = subprocess.run(
                        ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=max(1.0, self._cleanup_grace),
                        check=False,
                    )
                    if completed.returncode != 0:
                        errors.append("taskkill tree termination failed")
                except (OSError, subprocess.SubprocessError):
                    errors.append("taskkill unavailable")
            try:
                self.process.wait(timeout=self._cleanup_grace)
            except subprocess.TimeoutExpired:
                errors.append("process leader did not settle")
            return self.process.poll() is not None and not errors, "windows-taskkill", errors

        if self._group_exists():
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except OSError as error:
                errors.append(f"SIGTERM:{type(error).__name__}")
        try:
            self.process.wait(timeout=self._cleanup_grace)
        except subprocess.TimeoutExpired:
            pass
        if not self._wait_group_gone(self._cleanup_grace):
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as error:
                errors.append(f"SIGKILL:{type(error).__name__}")
            try:
                self.process.wait(timeout=self._cleanup_grace)
            except subprocess.TimeoutExpired:
                pass
        quiescent = self._wait_group_gone(self._cleanup_grace)
        if not quiescent:
            errors.append("process group remains alive after SIGKILL")
        return quiescent, "posix-process-group", errors

    def interrupt(self, reason: str) -> None:
        """Request termination without settling the provider result."""
        normalized = str(reason or "aborted").strip()[:128] or "aborted"
        with self._lock:
            if self._interrupt_reason is None:
                self._interrupt_reason = normalized
                _append_event(
                    self.ledger_path,
                    _event(
                        self.id,
                        "execution.interrupt_requested",
                        provider=self.provider,
                        reason=normalized,
                    ),
                )
            self._terminate_tree()

    def settle(self, *, stop_reason: str, output: str = "") -> RunResult:
        """Persist exactly one provider result; output is represented by digest only."""
        if stop_reason not in RUN_STOP_REASONS:
            raise ExecutionBackendError(f"unsupported run stop reason: {stop_reason}")
        with self._lock:
            if self._result is not None:
                if self._result.stop_reason != stop_reason:
                    raise ExecutionBackendError("run result was already settled differently")
                return self._result
            returncode = self.process.poll()
            if returncode is None:
                raise ExecutionBackendError("cannot settle a running process")
            result = RunResult(
                run_id=self.id,
                returncode=int(returncode),
                stop_reason=stop_reason,
                output_present=bool(output),
                output_sha256=_digest_text(output) if output else None,
            )
            _append_event(
                self.ledger_path,
                _event(
                    self.id,
                    "execution.result",
                    provider=self.provider,
                    returncode=result.returncode,
                    stop_reason=result.stop_reason,
                    output_present=result.output_present,
                    output_sha256=result.output_sha256,
                ),
            )
            self._result = result
            return result

    def dispose(self) -> CleanupResult:
        """Reach process-tree quiescence and release resources exactly once."""
        with self._lock:
            if self._cleanup is not None:
                return CleanupResult(
                    run_id=self._cleanup.run_id,
                    quiescent=self._cleanup.quiescent,
                    idempotent=True,
                    tree_scope=self._cleanup.tree_scope,
                    errors=self._cleanup.errors,
                )
            quiescent, tree_scope, errors = self._terminate_tree()
            if self._watchdog_fd is not None:
                try:
                    os.close(self._watchdog_fd)
                except OSError as error:
                    errors.append(f"close_watchdog:{type(error).__name__}")
                self._watchdog_fd = None
            for name in ("stdin", "stdout", "stderr"):
                stream = getattr(self.process, name, None)
                if stream is None or stream.closed:
                    continue
                try:
                    stream.close()
                except OSError as error:
                    errors.append(f"close_{name}:{type(error).__name__}")
            cleanup = CleanupResult(
                run_id=self.id,
                quiescent=quiescent,
                idempotent=False,
                tree_scope=tree_scope,
                errors=tuple(errors),
            )
            _append_event(
                self.ledger_path,
                _event(
                    self.id,
                    "execution.disposed",
                    provider=self.provider,
                    quiescent=cleanup.quiescent,
                    tree_scope=cleanup.tree_scope,
                    error_count=len(cleanup.errors),
                    errors_sha256=(
                        _digest_text("\n".join(cleanup.errors)) if cleanup.errors else None
                    ),
                ),
            )
            self._cleanup = cleanup
            return cleanup


class ExecutionBackend:
    """Start provider processes only after a durable non-secret request fact."""

    def __init__(self, *, cleanup_grace: float = 0.5) -> None:
        if cleanup_grace <= 0:
            raise ValueError("cleanup_grace must be positive")
        self.cleanup_grace = cleanup_grace

    def start(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        ledger_path: Path,
        provider: str,
        stdin: int | TextIO | None = subprocess.PIPE,
        stdout: int | TextIO | None = subprocess.PIPE,
        stderr: int | TextIO | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> RunHandle:
        if not command:
            raise ExecutionBackendError("execution command must not be empty")
        root = cwd.expanduser().resolve()
        run_id = "run-" + uuid.uuid4().hex[:24]
        _append_event(
            ledger_path,
            _event(
                run_id,
                "execution.requested",
                provider=provider,
                command_sha256=_digest_text("\0".join(str(value) for value in command)),
                workspace_id=_workspace_identifier(root),
                parent_death_watchdog=os.name != "nt",
            ),
        )
        selected_environment = dict(environment or os.environ)
        executable = str(command[0])
        resolved_executable = shutil.which(
            executable,
            path=selected_environment.get("PATH"),
        )
        if resolved_executable is None:
            _append_event(
                ledger_path,
                _event(
                    run_id,
                    "execution.start_failed",
                    provider=provider,
                    error_type="ExecutableNotFound",
                ),
            )
            raise ExecutionBackendError(
                f"provider process did not start: executable not found: {executable}"
            )
        options: dict[str, Any] = {
            "cwd": root,
            "stdin": stdin,
            "stdout": stdout,
            "stderr": stderr,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "env": {
                **selected_environment,
                "SULDE_MANAGED_RUN_ID": run_id,
                "SULDE_MANAGED_PARENT_PID": str(os.getpid()),
            },
        }
        watchdog_fd: int | None = None
        watchdog_read_fd: int | None = None
        launch_command = list(command)
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
            watchdog_read_fd, watchdog_fd = os.pipe()
            os.set_inheritable(watchdog_read_fd, True)
            options["pass_fds"] = (watchdog_read_fd,)
            launch_command = [
                sys.executable,
                str(Path(__file__).with_name("managed_process_wrapper.py")),
                "--parent-fd",
                str(watchdog_read_fd),
                "--",
                *launch_command,
            ]
        try:
            process = subprocess.Popen(launch_command, **options)
        except (OSError, subprocess.SubprocessError) as error:
            for descriptor in (watchdog_read_fd, watchdog_fd):
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
            _append_event(
                ledger_path,
                _event(
                    run_id,
                    "execution.start_failed",
                    provider=provider,
                    error_type=type(error).__name__,
                ),
            )
            raise ExecutionBackendError(f"provider process did not start: {error}") from error
        if watchdog_read_fd is not None:
            os.close(watchdog_read_fd)
        windows_job = _windows_job_for(process)
        try:
            _append_event(
                ledger_path,
                _event(
                    run_id,
                    "execution.started",
                    provider=provider,
                    pid=process.pid,
                    tree_scope=(
                        "windows-job"
                        if windows_job is not None
                        else "windows-taskkill"
                        if os.name == "nt"
                        else "posix-process-group"
                    ),
                    parent_death_watchdog=os.name != "nt",
                ),
            )
        except (OSError, TypeError, ValueError) as error:
            if watchdog_fd is not None:
                os.close(watchdog_fd)
                watchdog_fd = None
            if windows_job is not None:
                _close_windows_handle(windows_job)
                windows_job = None
            elif process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass
            try:
                process.wait(timeout=max(1.0, self.cleanup_grace * 4))
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except OSError:
                        pass
                else:
                    process.kill()
                process.wait(timeout=2)
            raise ExecutionBackendError(
                f"provider start checkpoint was not durable: {error}"
            ) from error
        return RunHandle(
            run_id=run_id,
            process=process,
            ledger_path=ledger_path,
            provider=provider,
            windows_job=windows_job,
            watchdog_fd=watchdog_fd,
            cleanup_grace=self.cleanup_grace,
        )
