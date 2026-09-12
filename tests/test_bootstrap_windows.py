from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(
    os.environ.get("SULDE_PLUGIN_UNDER_TEST", Path(__file__).resolve().parents[1])
)
BOOTSTRAP = ROOT / "scripts" / "kb" / "bootstrap.sh"
GIT_BASH = (
    Path(r"C:\Program Files\Git\bin\bash.exe")
    if os.name == "nt"
    else Path(shutil.which("bash") or "")
)
BASH = GIT_BASH


def to_msys_path(path: Path) -> str:
    posix = path.resolve().as_posix()
    if len(posix) >= 3 and posix[1] == ":":
        return f"/{posix[0].lower()}{posix[2:]}"
    return posix


def write_fastembed_stub(modules: Path) -> None:
    fastembed = modules / "fastembed"
    cross_encoder = fastembed / "rerank" / "cross_encoder"
    cross_encoder.mkdir(parents=True)
    (fastembed / "__init__.py").write_text(
        "class TextEmbedding:\n"
        "    def __init__(self, *args, **kwargs): pass\n",
        encoding="utf-8",
    )
    (fastembed / "rerank" / "__init__.py").write_text("", encoding="utf-8")
    (cross_encoder / "__init__.py").write_text(
        "class TextCrossEncoder:\n"
        "    def __init__(self, *args, **kwargs): pass\n",
        encoding="utf-8",
    )


@unittest.skipUnless(BASH.is_file(), "requires bash")
class BootstrapLauncherTest(unittest.TestCase):
    @unittest.skipUnless(
        os.name == "nt" and GIT_BASH.exists(),
        "requires Windows Git Bash",
    )
    def test_uses_scripts_python_from_native_windows_venv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            kb_home = temp / "kb"
            modules = temp / "modules"
            kb_home.mkdir()
            modules.mkdir()

            for module in ("jieba", "cryptography", "yaml"):
                (modules / f"{module}.py").write_text("", encoding="utf-8")
            write_fastembed_stub(modules)
            (kb_home / "kb.db").touch()
            (kb_home / "memory.db").touch()

            env = os.environ.copy()
            env["SULDE_KB_HOME"] = to_msys_path(kb_home)
            env["SULDE_CLAUDE_SETTINGS"] = str(temp / "settings.json")
            env["PYTHONPATH"] = str(modules)

            result = subprocess.run(
                [str(GIT_BASH), to_msys_path(BOOTSTRAP), "--host", "claude"],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )

            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            )
            self.assertTrue((kb_home / "venv" / "Scripts" / "python.exe").is_file())
            self.assertIn("Sulde KB bootstrap complete", result.stdout)

    def test_generated_launchers_use_native_source_hint_before_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            kb_home = temp / "kb"
            modules = temp / "modules"
            settings = temp / "settings.json"
            kb_home.mkdir()
            modules.mkdir()

            for module in ("jieba", "cryptography", "yaml"):
                (modules / f"{module}.py").write_text("", encoding="utf-8")
            write_fastembed_stub(modules)
            (kb_home / "kb.db").touch()
            (kb_home / "memory.db").touch()

            env = os.environ.copy()
            env["SULDE_KB_HOME"] = to_msys_path(kb_home)
            env["SULDE_CLAUDE_SETTINGS"] = str(settings)
            env["PYTHONPATH"] = str(modules)

            result = subprocess.run(
                [str(GIT_BASH), to_msys_path(BOOTSTRAP), "--host", "claude"],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            )

            launchers = {
                "sulde-statusline.py": ("scripts/kb/sulde-statusline.py", "statusline"),
                "kb-index": ("scripts/kb/kb-index", "python"),
                "sulde-kb-mcp": ("scripts/kb/kb-mcp", "python"),
                "mem-sync": ("scripts/kb/mem-sync.py", "python"),
                "intent-guardian": ("scripts/kb/intent-guardian.py", "python"),
            }
            for launcher_name, (target_relative, target_kind) in launchers.items():
                with self.subTest(launcher=launcher_name):
                    launcher = kb_home / "bin" / launcher_name
                    source = launcher.read_text(encoding="utf-8")
                    definitions, separator, _ = source.partition("\ntarget, override_used = resolve()")
                    self.assertTrue(separator, "launcher resolve boundary not found")
                    namespace: dict[str, object] = {"__file__": str(launcher)}
                    with mock.patch.object(os, "execve"):
                        exec(compile(definitions, str(launcher), "exec"), namespace)

                    self.assertEqual(namespace["TARGET_KIND"], target_kind)
                    codex_cached = (
                        temp
                        / ".codex/plugins/cache/sulde-local/sulde/2.10.3/runtime"
                        / target_relative
                    )
                    self.assertEqual(namespace["_version_key"](str(codex_cached)), (2, 10, 3))
                    hint = namespace["HINT"]
                    parts = target_relative.split("/")
                    self.assertTrue(os.path.isfile(os.path.join(hint, *parts)))
                    override_env = namespace["OVERRIDE_ENV"]
                    with (
                        mock.patch.dict(os.environ, {override_env: ""}),
                        mock.patch.object(
                            namespace["glob"],
                            "glob",
                            side_effect=AssertionError("cache fallback was consulted"),
                        ),
                    ):
                        resolved, override_used = namespace["resolve"]()
                    self.assertFalse(override_used)
                    self.assertEqual(
                        Path(resolved).resolve(), (ROOT / target_relative).resolve()
                    )

            launcher = kb_home / "bin" / "sulde-kb-mcp"
            target = ROOT / "scripts" / "kb" / "kb-mcp"
            fake_result = subprocess.CompletedProcess([], 0)
            with (
                mock.patch.dict(
                    os.environ,
                    {"SULDE_KB_HOME": str(kb_home)},
                ),
                mock.patch.object(sys, "argv", [str(launcher), "--probe"]),
                mock.patch.object(os, "execve") as reexec,
                mock.patch.object(subprocess, "run", return_value=fake_result) as run,
                self.assertRaises(SystemExit) as exit_context,
            ):
                runpy.run_path(str(launcher), run_name="__main__")
            self.assertEqual(exit_context.exception.code, 0)
            self.assertGreaterEqual(reexec.call_count, 1)
            self.assertEqual(
                Path(reexec.call_args_list[0].args[0]).resolve(),
                (
                    kb_home
                    / ("venv/Scripts/python.exe" if os.name == "nt" else "venv/bin/python")
                ).resolve(),
            )
            if os.name == "nt":
                run.assert_called_once()
            else:
                # The stable Python launcher now executes its target in-process;
                # kb-mcp then performs the one real process replacement into the
                # long-lived server. A returning execve mock exposes both calls.
                self.assertEqual(reexec.call_count, 2)
                run.assert_not_called()
                server_command = reexec.call_args_list[1].args[1]
                self.assertEqual(
                    Path(server_command[1]).resolve(),
                    (ROOT / "tools" / "kb-mcp" / "server.py").resolve(),
                )

    def test_generated_mcp_launcher_handshakes_without_bash_on_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            kb_home = temp / "kb"
            modules = temp / "modules"
            settings = temp / "settings.json"
            kb_home.mkdir()
            modules.mkdir()

            for module in ("jieba", "cryptography", "yaml"):
                (modules / f"{module}.py").write_text("", encoding="utf-8")
            write_fastembed_stub(modules)
            (kb_home / "kb.db").touch()
            (kb_home / "memory.db").touch()

            environment = os.environ.copy()
            environment["SULDE_KB_HOME"] = to_msys_path(kb_home)
            environment["SULDE_CLAUDE_SETTINGS"] = str(settings)
            environment["PYTHONPATH"] = str(modules)
            result = subprocess.run(
                [str(GIT_BASH), to_msys_path(BOOTSTRAP), "--host", "claude"],
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            empty_path = temp / "empty-path"
            empty_path.mkdir()
            minimal_environment = {
                "PATH": str(empty_path),
                "PYTHONDONTWRITEBYTECODE": "1",
                "SULDE_KB_HOME": str(kb_home),
            }
            for name in (
                "SYSTEMROOT",
                "WINDIR",
                "USERPROFILE",
                "HOME",
                "TEMP",
                "TMP",
            ):
                value = os.environ.get(name)
                if value:
                    minimal_environment[name] = value
            request = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05"},
                },
                separators=(",", ":"),
            )
            handshake = subprocess.run(
                [
                    str(
                        kb_home
                        / "venv"
                        / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                    ),
                    str(kb_home / "bin" / "sulde-kb-mcp"),
                ],
                input=request + "\n",
                env=minimal_environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )

            self.assertEqual(handshake.returncode, 0, handshake.stderr)
            response_line = handshake.stdout.strip().splitlines()[-1]
            print(response_line)
            response = json.loads(response_line)
            self.assertEqual(response["result"]["serverInfo"]["name"], "sulde-kb")

    def test_generated_index_launcher_runs_utf8_commands_without_bash_on_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            kb_home = temp / "kb"
            modules = temp / "modules"
            settings = temp / "settings.json"
            kb_home.mkdir()
            modules.mkdir()

            for module in ("jieba", "cryptography", "yaml"):
                (modules / f"{module}.py").write_text("", encoding="utf-8")
            write_fastembed_stub(modules)
            (kb_home / "kb.db").touch()
            (kb_home / "memory.db").touch()

            bootstrap_environment = os.environ.copy()
            bootstrap_environment["SULDE_KB_HOME"] = to_msys_path(kb_home)
            bootstrap_environment["SULDE_CLAUDE_SETTINGS"] = str(settings)
            bootstrap_environment["PYTHONPATH"] = str(modules)
            result = subprocess.run(
                [str(GIT_BASH), to_msys_path(BOOTSTRAP), "--host", "claude"],
                env=bootstrap_environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            complete_line = next(
                line
                for line in result.stdout.splitlines()
                if line.startswith("Sulde KB bootstrap complete:")
            )
            print(complete_line)

            fixture_root = temp / "fixture-root"
            fake_index = fixture_root / "scripts" / "kb" / "kb-index"
            shared_cli = fixture_root / "hooks" / "lib" / "kb_cli.py"
            fake_index.parent.mkdir(parents=True)
            shared_cli.parent.mkdir(parents=True)
            shutil.copy2(ROOT / "scripts" / "kb" / "kb-index", fake_index)
            shutil.copy2(ROOT / "hooks" / "lib" / "kb_cli.py", shared_cli)
            fake_targets = (
                fixture_root / "tools" / "kb-index" / "search.py",
                fixture_root / "tools" / "kb-index" / "memory.py",
            )
            for target in fake_targets:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    "import json, sys\n"
                    "print(json.dumps({'args': sys.argv[1:]}, ensure_ascii=False))\n",
                    encoding="utf-8",
                )
            empty_path = temp / "empty-path"
            empty_path.mkdir()
            minimal_environment = {
                "PATH": str(empty_path),
                "PYTHONDONTWRITEBYTECODE": "1",
                "SULDE_KB_HOME": str(kb_home),
                "SULDE_KB_INDEX": str(fake_index),
            }
            for name in (
                "SYSTEMROOT",
                "WINDIR",
                "USERPROFILE",
                "HOME",
                "TEMP",
                "TMP",
            ):
                value = os.environ.get(name)
                if value:
                    minimal_environment[name] = value

            python = kb_home / "venv" / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"
            )
            launcher = kb_home / "bin" / "kb-index"
            annotation = json.dumps(
                {"entities": [], "edges": []},
                separators=(",", ":"),
            )
            cases = (
                (["search", "含中文查询", "-k", "1", "--json"], ["含中文查询", "-k", "1", "--json"]),
                (["mem-annotate", annotation], ["annotate", annotation]),
            )
            for arguments, expected in cases:
                with self.subTest(arguments=arguments):
                    completed = subprocess.run(
                        [str(python), str(launcher), *arguments],
                        env=minimal_environment,
                        capture_output=True,
                        timeout=20,
                        check=False,
                    )
                    self.assertEqual(
                        completed.returncode,
                        0,
                        completed.stderr.decode("utf-8", errors="replace"),
                    )
                    response = json.loads(completed.stdout)
                    self.assertEqual(response["args"], expected)
                    print(completed.stdout.decode("utf-8").strip())

            minimal_environment["SULDE_KB_INDEX"] = str(
                ROOT / "scripts" / "kb" / "kb-index"
            )
            home = subprocess.run(
                [str(python), str(launcher), "home"],
                env=minimal_environment,
                capture_output=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(home.returncode, 0, home.stderr)
            self.assertEqual(home.stdout.decode("utf-8").splitlines(), [str(kb_home)])
            print(home.stdout.decode("utf-8").strip())

    def test_bootstrap_source_index_calls_use_resolved_venv_python(self) -> None:
        source = BOOTSTRAP.read_text(encoding="utf-8")
        expected = (
            'SULDE_KB_HOME="$KB_HOME" "$VENV_PYTHON" "$SCRIPT_DIR/kb-index" build',
            'SULDE_KB_HOME="$KB_HOME" "$VENV_PYTHON" "$SCRIPT_DIR/kb-index" mem-init',
        )
        for invocation in expected:
            with self.subTest(invocation=invocation):
                self.assertEqual(source.count(invocation), 1)

    def test_bootstrap_declares_fast_launcher_refresh_without_full_initialization(self) -> None:
        source = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn("--launchers-only", source)
        self.assertIn("export PYTHONDONTWRITEBYTECODE", source)
        self.assertIn('launcher_contract.py" install', source)
        self.assertLess(
            source.index('if [ "$LAUNCHERS_ONLY" = true ]'),
            source.index('if VENV_PYTHON=$(resolve_venv_python)'),
        )


if __name__ == "__main__":
    unittest.main()
