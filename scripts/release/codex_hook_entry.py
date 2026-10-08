"""Versioned, cache-independent POSIX Hook transport; never decision authority."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

SCHEMA = "sulde-codex-stable-hook-v1"
FILES = ("run-hook.sh", "_recovery_defer.py", "_hook_observer.py")
LIMIT = 262144
MARKER = "# sulde-stable-entry-v1 "
PIN_BEGIN = "# sulde-stable-pin-begin-v1"
PIN_END = "# sulde-stable-pin-end-v1"
PATH_SOURCE = '''# sulde-stable-path-begin-v1
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PLUGIN_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
# sulde-stable-path-end-v1'''
PATH_REPLACEMENT = 'SCRIPT_DIR=${0%/*}\nPLUGIN_DIR=${SCRIPT_DIR%/*}'
PIN_SOURCE = '''PINNED_OBSERVER=
PINNED_FALLBACK=
if [ -f "$SCRIPT_DIR/_hook_observer.py" ] && command exec 8<"$SCRIPT_DIR/_hook_observer.py"; then
  PINNED_OBSERVER=8
fi
if [ -f "$SCRIPT_DIR/_recovery_defer.py" ] && command exec 9<"$SCRIPT_DIR/_recovery_defer.py"; then
  PINNED_FALLBACK=9
fi'''
RECOVERY_CALL = '''run_pre_tool_fallback() {
  RECOVERY_OUTPUT=$(printf '%s' "$HOOK_PAYLOAD" | run_pinned_module 7)
  RECOVERY_STATUS=$?
  if [ "$RECOVERY_STATUS" -eq 0 ]; then
    [ -z "$RECOVERY_OUTPUT" ] || printf '%s\\n' "$RECOVERY_OUTPUT"
    return 0
  fi
'''

# Failure-only: authenticate existing runtime bytes before importing its existing
# native recovery route. This is not a second policy or a copy of its dependency
# tree. No recovery command is executed here; only the original Pre adapter runs.
RECOVERY_HELPER = r'''
def main():
    import contextlib, hashlib, io, json, os, stat, sys, types
    from pathlib import Path
    def read(path, limit=16777216):
        if path != path.resolve():
            raise ValueError("recovery path alias")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            data = stream.read(limit + 1)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022 or len(data) > limit:
            raise ValueError("untrusted recovery file")
        return data
    try:
        home = Path(os.environ["SULDE_HOME"]).resolve()
        manifest = json.loads(read(home / "bin/.sulde-launchers.json", 262144))
        if manifest.get("schema") != "sulde-launcher-install-v1":
            raise ValueError("unknown launcher manifest")
        interpreter = Path(manifest["interpreter"]).resolve(strict=True)
        if interpreter != Path(sys.executable).resolve(strict=True) or hashlib.sha256(interpreter.read_bytes()).hexdigest() != manifest.get("interpreter_sha256"):
            raise ValueError("recovery interpreter identity mismatch")
        runtime = Path(manifest["source_root"])
        if not runtime.is_absolute() or runtime.name != "runtime" or runtime != runtime.resolve():
            raise ValueError("untrusted recovery runtime")
        digest = hashlib.sha256()
        bytecode_present = False
        for path in sorted(runtime.rglob("*")):
            relative = path.relative_to(runtime)
            if path.is_symlink() or ".git" in relative.parts:
                raise ValueError("unsafe recovery runtime tree")
            # Match RepairTarget.desired(ignore_bytecode=True), while ensuring
            # the interpreter never reads that unverified bytecode below.
            if "__pycache__" in relative.parts or path.suffix.casefold() == ".pyc":
                bytecode_present = True
                continue
            if path.is_dir():
                continue
            name = relative.as_posix().encode("utf-8")
            digest.update(len(name).to_bytes(8, "big")); digest.update(name)
            digest.update(read(path))
        tree = digest.hexdigest()
        generation = json.loads(read(runtime.parent / ".codex-plugin/generation.json", 262144))
        if (manifest.get("runtime_tree_sha256") != tree or generation.get("runtime_tree_sha256") != tree
                or generation.get("schema") != "sulde-delivery-generation-v1" or generation.get("provider") != "codex"
                or generation.get("generation") != manifest.get("generation")
                or generation.get("generation") != str(generation.get("plugin_version")) + ":" + tree):
            raise ValueError("recovery generation mismatch")
        surface = manifest.get("codex_hook_file_sha256")
        if not isinstance(surface, dict):
            raise ValueError("recovery adapter identities missing")
        contents = {}
        for name, expected in surface.items():
            path = Path(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("recovery adapter path escape")
            contents[name] = read(runtime.parent / path)
            if hashlib.sha256(contents[name]).hexdigest() != expected:
                raise ValueError("recovery adapter drift")
        # Only now import the existing, whole-tree-verified resolver. It checks
        # current manifest/event binding without requiring the broken launcher.
        sys.pycache_prefix = "/dev/null/sulde-verified-recovery"
        sys.path.insert(0, str(runtime / "scripts/kb"))
        import launcher_contract
        if not bytecode_present and launcher_contract.runtime_digest(runtime) != manifest.get("runtime_sha256"):
            raise ValueError("recovery runtime identity mismatch")
        adapter = launcher_contract.resolve_codex_hook_adapter(home, runtime, "pre-tool-use")
        for name, source, filename in (
            ("_adapter_common", contents["scripts/_adapter_common.py"], str(runtime.parent / "scripts/_adapter_common.py")),
            ("_recovery_defer", None, "<verified-pinned-recovery-defer>"),
        ):
            if source is None:
                os.lseek(9, 0, os.SEEK_SET)
                source = os.read(9, 262145)
            module = types.ModuleType(name)
            module.__file__ = filename
            sys.modules[name] = module
            exec(compile(source, filename, "exec"), module.__dict__)
        os.environ["SULDE_CODEX_FALLBACK_ONLY"] = "1"
        os.environ["SULDE_SOURCE_ROOT"] = str(runtime)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            try:
                exec(compile(contents["scripts/pre-tool-use.py"], str(adapter), "exec"), {"__name__": "__main__", "__file__": str(adapter)})
            except SystemExit as result:
                if result.code not in (None, 0):
                    raise ValueError("recovery adapter failed")
        print(output.getvalue(), end="")
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError):
        print("sulde: verified_recovery_unavailable; retaining strict fallback", file=sys.stderr)
        return 65
'''


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError("unsafe hook entry file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(LIMIT + 1)
        if not data or len(data) > LIMIT:
            raise ValueError("invalid hook entry size")
        return data
    finally:
        os.close(fd)


def _directories(root, target):
    target.relative_to(root)
    for path in (root, *reversed(target.relative_to(root).parents)):
        # Relative parents are inspected below; root is independently anchored.
        if not path.is_absolute():
            path = root / path
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise ValueError("unsafe hook entry directory")
    if target.exists() or target.is_symlink():
        info = target.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError("unsafe hook entry directory")


def _python_block(source):
    begin, end = "# sulde-stable-python-begin-v1", "# sulde-stable-python-end-v1"
    if source.count(begin) != 1 or source.count(end) != 1:
        raise ValueError("stable hook interpreter interface mismatch")
    first = source.index(begin)
    last = source.index(end) + len(end)
    if last <= first:
        raise ValueError("stable hook interpreter interface order mismatch")
    return source[first:last]


def _compiled_shell(source):
    source = source.decode("utf-8")
    block = PIN_BEGIN + "\n" + PIN_SOURCE + "\n" + PIN_END
    if source.count(PIN_BEGIN) != 1 or source.count(PIN_END) != 1 or source.count(block) != 1:
        raise ValueError("stable hook pin interface mismatch")
    if source.count(PATH_SOURCE) != 1:
        raise ValueError("stable hook path interface mismatch")
    if source.count("run_pre_tool_fallback() {\n") != 1:
        raise ValueError("stable hook recovery interface mismatch")
    # Paths cannot be reopened after verification. Existing transport and policy
    # functions consume only the held helpers or the normal signed bridge.
    replacement = "PINNED_OBSERVER=8\nPINNED_FALLBACK=9\nSCRIPT_DIR=/dev/null/sulde-stable-entry"
    return source.replace(block, replacement).replace(PATH_SOURCE, PATH_REPLACEMENT).replace(_python_block(source), 'PYTHON=$SULDE_STABLE_INTERPRETER').replace("run_pre_tool_fallback() {\n", RECOVERY_CALL).encode("utf-8")


# This tiny loader is embedded in the atomically published executable, so it is
# not imported from a directory the plugin registry can remove. All helper bytes
# are copied before execution, preventing hash/check -> pathname reopen races.
LOADER = r'''
import hashlib, os, stat, sys
def fail():
    if len(sys.argv) > 1 and sys.argv[1] == "pre-tool-use":
        print('{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Sulde stable Hook entry unavailable; action was not executed."}}')
    print("sulde: stable_hook_entry_unavailable; hook_observer_unavailable; coverage_blind_spot", file=sys.stderr)
    raise SystemExit(0)
try:
    if sys.version_info < (3, 10):
        fail()
    executable = D["interpreter"]["path"]
    real_executable = D["interpreter"].get("real_path", executable)
    if os.path.realpath(executable) != real_executable:
        fail()
    interpreter_fd = os.open(real_executable, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(interpreter_fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        executable_bytes = stream.read(16777217)
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or len(executable_bytes) > 16777216 or hashlib.sha256(executable_bytes).hexdigest() != D["interpreter"]["sha256"]:
        fail()
    # Reserve the wrapper's two documented scratch slots before any opens;
    # inherited FDs must not cause the held directory to land in slot 8 or 9.
    os.dup2(0, 8, inheritable=False)
    os.dup2(0, 9, inheritable=False)
    os.dup2(0, 7, inheritable=False)
    root = D["root"]
    directory = os.path.join(root, "hook-entry", D["bundle_id"], "scripts")
    # Open each directory relative to a held descriptor, disallowing symlinks.
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    info = os.fstat(descriptor)
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        fail()
    for part in ("hook-entry", D["bundle_id"], "scripts"):
        previous = descriptor
        descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=previous)
        os.close(previous)
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            fail()
    contents = {}
    for name, digest in D["files"].items():
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                fail()
            data = stream.read(262145)
        if len(data) > 262144 or hashlib.sha256(data).hexdigest() != digest:
            fail()
        contents[name] = data
    shell = contents["run-hook.sh"].decode("utf-8")
    if shell.count(PIN_BLOCK) != 1:
        fail()
    if shell.count(PATH_BLOCK) != 1:
        fail()
    shell = shell.replace(PIN_BLOCK, PIN_REPLACEMENT).replace(PATH_BLOCK, PATH_REPLACEMENT)
    if shell.count(PYTHON_BLOCK) != 1:
        fail()
    shell = shell.replace(PYTHON_BLOCK, 'PYTHON=$SULDE_STABLE_INTERPRETER')
    if shell.count("run_pre_tool_fallback() {\n") != 1:
        fail()
    shell = shell.replace("run_pre_tool_fallback() {\n", RECOVERY_CALL)
    if hashlib.sha256(shell.encode("utf-8")).hexdigest() != D["shell_sha256"]:
        fail()
    # Unlinked regular files are portable to Python 3.10/macOS. Create relative
    # to the held directory, unlink before use, and never accept caller FDs.
    contents["verified-recovery"] = RECOVERY_HELPER.encode("utf-8")
    for name, target in (("_hook_observer.py", 8), ("_recovery_defer.py", 9), ("verified-recovery", 7)):
        temporary = ".held-" + os.urandom(16).hex()
        fd = os.open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
        os.unlink(temporary, dir_fd=descriptor)
        data = contents[name]
        while data:
            data = data[os.write(fd, data):]
        os.lseek(fd, 0, os.SEEK_SET)
        os.dup2(fd, target, inheritable=True)
        if fd != target:
            os.close(fd)
    os.close(descriptor)
    env = dict(os.environ)
    env["SULDE_HOME"] = root
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["SULDE_STABLE_INTERPRETER"] = executable
    reader, writer = os.pipe()
    child = os.posix_spawn("/bin/sh", ["/bin/sh", "-c", shell, os.path.join(directory, "run-hook.sh"), *sys.argv[1:]], env,
        file_actions=[(os.POSIX_SPAWN_DUP2, writer, 1), (os.POSIX_SPAWN_CLOSE, reader), (os.POSIX_SPAWN_CLOSE, writer)])
    os.close(writer)
    output = bytearray()
    while True:
        chunk = os.read(reader, 65536)
        if not chunk:
            break
        output.extend(chunk)
        if len(output) > 2097152:
            os.kill(child, 9)
            os.waitpid(child, 0)
            fail()
    os.close(reader)
    _, status = os.waitpid(child, 0)
    if os.waitstatus_to_exitcode(status):
        fail()
    sys.stdout.buffer.write(b"sulde-hook-entry-complete-v1:" + output)
except (OSError, ValueError, KeyError, TypeError, UnicodeError):
    fail()
'''


def _bootstrap(description):
    core = json.loads(_json({key: value for key, value in description.items() if key != "bootstrap_sha256"}))
    encoded = base64.b64encode(_json(core).encode()).decode()
    block = PIN_BEGIN + "\n" + PIN_SOURCE + "\n" + PIN_END
    code = "D = " + repr(core) + "\nPIN_BLOCK = " + repr(block) + "\nPIN_REPLACEMENT = " + repr("PINNED_OBSERVER=8\nPINNED_FALLBACK=9\nSCRIPT_DIR=/dev/null/sulde-stable-entry") + "\nPATH_BLOCK = " + repr(PATH_SOURCE) + "\nPATH_REPLACEMENT = " + repr(PATH_REPLACEMENT) + "\nPYTHON_BLOCK = " + repr(core["python_block"]) + "\nRECOVERY_CALL = " + repr(RECOVERY_CALL) + "\nRECOVERY_HELPER = " + repr(RECOVERY_HELPER) + "\n" + LOADER
    quoted = "'" + code.replace("'", "'\"'\"'") + "'"
    python = "'" + core["interpreter"]["path"].replace("'", "'\"'\"'") + "'"
    return ("#!/bin/sh\n" + MARKER + encoded + "\n"
            "P=" + python + "\nif [ ! -f \"$P\" ] || [ ! -x \"$P\" ]; then\n"
            "  if [ \"${1:-}\" = pre-tool-use ]; then printf '%s\\n' '{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"Sulde stable Hook entry requires Python 3.10; action was not executed.\"}}'; fi\n"
            "  echo 'sulde: interpreter_unavailable; hook_observer_unavailable; coverage_blind_spot' >&2\n"
            "  exit 0\nfi\nexec \"$P\" -B -I -S -c " + quoted + " \"$@\"\n").encode("utf-8")


def describe(plugin_root: Path, sulde_root: Path, *, interpreter: Path | None = None) -> dict:
    root = Path(os.path.abspath(sulde_root))
    sources = {name: _regular(Path(plugin_root) / "scripts" / name) for name in FILES}
    files = {name: _sha(source) for name, source in sources.items()}
    identity = {"schema": SCHEMA, "files": files, "shell_sha256": _sha(_compiled_shell(sources["run-hook.sh"]))}
    invocation = Path(os.path.abspath(interpreter or sys.executable))
    executable = invocation.resolve(strict=True)
    info = executable.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or not os.access(executable, os.X_OK):
        raise ValueError("unsafe stable hook interpreter")
    with executable.open("rb") as stream:
        executable_bytes = stream.read(16777217)
    if len(executable_bytes) > 16777216:
        raise ValueError("stable hook interpreter exceeds bound")
    descriptor = {**identity, "root": str(root), "bundle_id": _sha(_json(identity).encode()), "python_block": _python_block(sources["run-hook.sh"].decode("utf-8")), "interpreter": {"path": str(invocation), "real_path": str(executable), "sha256": _sha(executable_bytes)}}
    descriptor["bootstrap_sha256"] = _sha(_bootstrap(descriptor))
    return descriptor


def snapshot_files(sulde_root: Path) -> list[Path]:
    return [Path(sulde_root) / "bin" / "sulde-codex-hook"]


def _validate_descriptor(descriptor):
    fields = {"schema", "files", "shell_sha256", "root", "bundle_id", "bootstrap_sha256", "interpreter", "python_block"}
    if not isinstance(descriptor, dict) or set(descriptor) != fields or descriptor["schema"] != SCHEMA:
        raise ValueError("invalid stable hook descriptor")
    files = descriptor["files"]
    if not isinstance(files, dict) or set(files) != set(FILES):
        raise ValueError("invalid stable hook inventory")
    for value in (*files.values(), descriptor["shell_sha256"], descriptor["bundle_id"], descriptor["bootstrap_sha256"]):
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("invalid stable hook digest")
    identity = {name: descriptor[name] for name in ("schema", "files", "shell_sha256")}
    if _sha(_json(identity).encode()) != descriptor["bundle_id"]:
        raise ValueError("invalid stable hook bundle identity")
    root = descriptor["root"]
    if not isinstance(root, str) or not os.path.isabs(root) or os.path.abspath(root) != root:
        raise ValueError("invalid stable hook root")
    interpreter = descriptor["interpreter"]
    if not isinstance(interpreter, dict) or set(interpreter) not in ({"path", "sha256"}, {"path", "real_path", "sha256"}) or not isinstance(interpreter["path"], str) or not os.path.isabs(interpreter["path"]):
        raise ValueError("invalid stable hook interpreter")
    if "real_path" in interpreter and (not isinstance(interpreter["real_path"], str) or not os.path.isabs(interpreter["real_path"])):
        raise ValueError("invalid stable hook interpreter target")
    digest = interpreter["sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("invalid stable hook interpreter digest")
    if not isinstance(descriptor["python_block"], str) or _python_block(descriptor["python_block"]) != descriptor["python_block"]:
        raise ValueError("invalid stable hook interpreter block")


def _bundle_verify(descriptor):
    _validate_descriptor(descriptor)
    root = Path(descriptor["root"])
    folder = root / "hook-entry" / descriptor["bundle_id"] / "scripts"
    _directories(root, folder)
    if any(_sha(_regular(folder / name)) != descriptor["files"][name] for name in FILES):
        raise ValueError("stable hook bundle digest mismatch")
    invocation = descriptor["interpreter"]["path"]
    real_executable = descriptor["interpreter"].get("real_path", invocation)
    if os.path.realpath(invocation) != real_executable:
        raise ValueError("stable hook interpreter alias drift")
    fd = os.open(real_executable, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        data = stream.read(16777217)
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or not info.st_mode & 0o111 or len(data) > 16777216 or _sha(data) != descriptor["interpreter"]["sha256"]:
        raise ValueError("stable hook interpreter drift")


def prepare(plugin_root: Path, sulde_root: Path, *, interpreter: Path | None = None) -> dict:
    descriptor = describe(plugin_root, sulde_root, interpreter=interpreter)
    root = Path(descriptor["root"])
    parent = root / "hook-entry"
    _directories(root, parent)
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = parent / descriptor["bundle_id"]
    if not destination.exists():
        # Aborted preparation leaves only an unreferenced directory, never a
        # partially selected generation. Existing bundles are never overwritten.
        temporary = Path(tempfile.mkdtemp(prefix=".prepare-", dir=parent))
        folder = temporary / "scripts"
        folder.mkdir(mode=0o700)
        for name in FILES:
            data = _regular(Path(plugin_root) / "scripts" / name)
            if _sha(data) != descriptor["files"][name]:
                raise ValueError("stable hook source changed during prepare")
            with (folder / name).open("xb") as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            (folder / name).chmod(0o444)
        os.rename(temporary, destination)
    _bundle_verify(descriptor)
    return descriptor


def publish(sulde_root: Path, descriptor: dict) -> Path:
    _validate_descriptor(descriptor)
    root = Path(os.path.abspath(sulde_root))
    if descriptor["root"] != str(root) or _sha(_bootstrap(descriptor)) != descriptor["bootstrap_sha256"]:
        raise ValueError("stable hook publication identity mismatch")
    _bundle_verify(descriptor)
    target = snapshot_files(root)[0]
    _directories(root, target.parent)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.is_symlink():
        raise ValueError("stable hook bootstrap is a symlink")
    fd, name = tempfile.mkstemp(prefix=".sulde-codex-hook-", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o700)
            stream.write(_bootstrap(descriptor)); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def verify(sulde_root: Path, expected: dict | None = None) -> dict:
    try:
        root = Path(os.path.abspath(sulde_root))
        _directories(root, root / "bin")
        raw = _regular(snapshot_files(sulde_root)[0])
        lines = raw.decode("utf-8").splitlines()
        if len(lines) < 2 or not lines[1].startswith(MARKER):
            raise ValueError("stable hook bootstrap marker missing")
        descriptor = json.loads(base64.b64decode(lines[1][len(MARKER):], validate=True))
        descriptor["bootstrap_sha256"] = _sha(raw)
        _validate_descriptor(descriptor)
        if descriptor["root"] != str(Path(os.path.abspath(sulde_root))):
            raise ValueError("stable hook bootstrap drift")
        if expected is not None:
            _validate_descriptor(expected)
            if descriptor != expected:
                raise ValueError("stable hook expected identity mismatch")
        elif raw != _bootstrap(descriptor):
            # With no sealed predecessor fact, only this generator can attest
            # its own bytes. Upgrades always pass their persisted old identity.
            raise ValueError("stable hook unbound generator identity")
        _bundle_verify(descriptor)
        return {"healthy": True, "issues": [], "bundle_id": descriptor["bundle_id"]}
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        return {"healthy": False, "issues": ["stable_hook_entry_invalid"], "bundle_id": None}
