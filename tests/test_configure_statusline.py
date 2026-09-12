from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(
    os.environ.get("SULDE_PLUGIN_UNDER_TEST", Path(__file__).resolve().parents[1])
)
CONFIGURATOR = ROOT / "scripts" / "kb" / "configure-statusline.py"
BOOTSTRAP = ROOT / "scripts" / "kb" / "bootstrap.sh"
WINDOWS_GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")
BASH = WINDOWS_GIT_BASH if os.name == "nt" else Path(shutil.which("bash") or "")

# Protect pre-existing bootstrap tests that predate injectable settings support.
# Every test in this module still passes its own tmpdir path explicitly.
_ORIGINAL_SULDE_CLAUDE_SETTINGS = os.environ.get("SULDE_CLAUDE_SETTINGS")
_SUITE_SETTINGS_TMP = tempfile.TemporaryDirectory(prefix="sulde-pytest-settings-")
os.environ["SULDE_CLAUDE_SETTINGS"] = str(
    Path(_SUITE_SETTINGS_TMP.name) / "settings.json"
)


def _cleanup_suite_settings() -> None:
    if _ORIGINAL_SULDE_CLAUDE_SETTINGS is None:
        os.environ.pop("SULDE_CLAUDE_SETTINGS", None)
    else:
        os.environ["SULDE_CLAUDE_SETTINGS"] = _ORIGINAL_SULDE_CLAUDE_SETTINGS
    _SUITE_SETTINGS_TMP.cleanup()


unittest.addModuleCleanup(_cleanup_suite_settings)


def to_msys_path(path: Path) -> str:
    posix = path.resolve().as_posix()
    if os.name == "nt" and len(posix) >= 3 and posix[1] == ":":
        return f"/{posix[0].lower()}{posix[2:]}"
    return posix


class ConfigureStatusLineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.kb_home = self.root / "KB Home with spaces"
        self.settings = self.root / "Claude Settings" / "settings.json"
        if os.name == "nt":
            self.venv_python = self.kb_home / "venv" / "Scripts" / "python.exe"
        else:
            self.venv_python = self.kb_home / "venv" / "bin" / "python"
        self.launcher = self.kb_home / "bin" / "sulde-statusline.py"
        self.venv_python.parent.mkdir(parents=True)
        self.venv_python.write_text("placeholder", encoding="utf-8")
        if os.name != "nt":
            self.venv_python.chmod(0o755)
        self.launcher.parent.mkdir(parents=True)
        self.launcher.write_text('print("sulde test")\n', encoding="utf-8")

    def run_configurator(
        self,
        *arguments: str,
        settings: Path | None = None,
        python_path: Path | None = None,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(CONFIGURATOR),
            *arguments,
            "--kb-home",
            str(self.kb_home),
            "--settings",
            str(settings or self.settings),
        ]
        if python_path is not None:
            command.extend(("--python", str(python_path)))
        return subprocess.run(
            command,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )

    def write_settings(self, value: dict[str, object]) -> bytes:
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        original = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        self.settings.write_bytes(original)
        return original

    def backups(self) -> list[Path]:
        return list(self.settings.parent.glob(f"{self.settings.name}.*.bak"))

    def test_install_handles_spaced_paths_and_json_escaping(self) -> None:
        result = self.run_configurator("--install")
        self.assertEqual(result.returncode, 0, result.stderr)
        raw = self.settings.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        command = parsed["statusLine"]["command"]
        self.assertIn(f'"{self.venv_python.resolve()}"', command)
        self.assertIn(f'"{self.launcher.resolve()}"', command)
        self.assertIn(json.dumps(str(self.venv_python.resolve()))[1:-1], raw)
        self.assertEqual(parsed["statusLine"]["type"], "command")

    def test_non_sulde_conflict_requires_force(self) -> None:
        original = {"model": "opus", "statusLine": {"type": "command", "command": "other"}}
        original_bytes = self.write_settings(original)
        refused = self.run_configurator("--install")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("non-Sulde", refused.stderr)
        self.assertEqual(self.settings.read_bytes(), original_bytes)
        self.assertEqual(self.backups(), [])

        forced = self.run_configurator("--install", "--force")
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertIn("sulde-statusline.py", json.loads(self.settings.read_text())["statusLine"]["command"])

        self.write_settings({"statusLine": None})
        null_conflict = self.run_configurator("--install")
        self.assertNotEqual(null_conflict.returncode, 0)
        self.assertIn("non-Sulde", null_conflict.stderr)

    def test_repeated_install_is_idempotent_without_extra_backup(self) -> None:
        original_bytes = self.write_settings({"theme": "dark"})
        first = self.run_configurator("--install")
        self.assertEqual(first.returncode, 0, first.stderr)
        installed_bytes = self.settings.read_bytes()
        first_backups = self.backups()
        self.assertEqual(len(first_backups), 1)
        self.assertEqual(first_backups[0].read_bytes(), original_bytes)

        second = self.run_configurator("--install")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("already up to date", second.stdout)
        self.assertEqual(self.settings.read_bytes(), installed_bytes)
        self.assertEqual(self.backups(), first_backups)

    def test_backup_retention_is_bounded_and_only_prunes_generated_names(self) -> None:
        self.write_settings({"theme": "dark"})
        unrelated = [
            self.settings.with_name(f"{self.settings.name}.manual.bak"),
            self.settings.with_name(
                f"{self.settings.name}.20000101T000000.000000Z.keep.bak"
            ),
        ]
        for path in unrelated:
            path.write_text("keep\n", encoding="utf-8")

        for index in range(6):
            action = "--install" if index % 2 == 0 else "--uninstall"
            result = self.run_configurator(action, "--backup-limit", "2")
            self.assertEqual(result.returncode, 0, result.stderr)

        generated_pattern = re.compile(
            rf"^{re.escape(self.settings.name)}\.\d{{8}}T\d{{6}}\.\d{{6}}Z"
            r"(?:\.[1-9]\d*)?\.bak$"
        )

        def generated_backups() -> list[Path]:
            return [
                path
                for path in self.settings.parent.iterdir()
                if generated_pattern.fullmatch(path.name)
            ]

        self.assertEqual(len(generated_backups()), 2)
        self.assertTrue(
            all(path.read_text(encoding="utf-8") == "keep\n" for path in unrelated)
        )

        for action in ("--install", "--uninstall"):
            result = self.run_configurator(action, "--backup-limit", "0")
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(generated_backups()), 4)

        help_result = self.run_configurator("--help")
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("default: 5", help_result.stdout)
        self.assertIn("0 disables pruning", help_result.stdout)

    def test_uninstall_removes_only_owned_status_line(self) -> None:
        retained = {"model": "sonnet", "hooks": {"Stop": [{"command": "keep-me"}]}}
        self.write_settings(retained)
        self.assertEqual(self.run_configurator("--install").returncode, 0)
        removed = self.run_configurator("--uninstall")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8")), retained)

        self.write_settings({**retained, "statusLine": {"type": "command", "command": "other"}})
        refused = self.run_configurator("--uninstall")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("non-Sulde", refused.stderr)

    def test_nested_existing_values_are_preserved(self) -> None:
        original = {
            "model": "opus",
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo 一"}]},
                    {"matcher": "Write", "hooks": []},
                ]
            },
            "enabledPlugins": {"sulde": True},
            "theme": "dark",
        }
        self.write_settings(original)
        installed = self.run_configurator("--install")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        result = json.loads(self.settings.read_text(encoding="utf-8"))
        del result["statusLine"]
        self.assertEqual(result, original)

    def test_dry_run_has_no_filesystem_side_effect(self) -> None:
        alternate = self.root / "not created" / "settings.json"
        result = self.run_configurator("--install", "--dry-run", settings=alternate)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dry-run: would write", result.stdout)
        self.assertIn("statusLine", result.stdout)
        self.assertFalse(alternate.parent.exists())

    def test_missing_venv_is_an_explicit_error(self) -> None:
        self.venv_python.unlink()
        result = self.run_configurator("--install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime file is missing", result.stderr)
        self.assertFalse(self.settings.exists())

    def test_check_runs_command_and_rejects_empty_output(self) -> None:
        installed = self.run_configurator("--install", python_path=Path(sys.executable))
        self.assertEqual(installed.returncode, 0, installed.stderr)
        checked = self.run_configurator("--check", python_path=Path(sys.executable))
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("sulde test", checked.stdout)
        self.assertIn("ms", checked.stdout)

        self.launcher.write_text("pass\n", encoding="utf-8")
        empty = self.run_configurator("--check", python_path=Path(sys.executable))
        self.assertNotEqual(empty.returncode, 0)
        self.assertIn("empty output", empty.stderr)

    def test_check_survives_cp936_strict_console_output(self) -> None:
        self.launcher.write_text(
            "import os, sys\n"
            "os.write(sys.stdout.fileno(), "
            "'\\x1b[33m待嵌 � 🙂\\x1b[0m\\n'.encode('utf-8'))\n",
            encoding="utf-8",
        )
        installed = self.run_configurator("--install", python_path=Path(sys.executable))
        self.assertEqual(installed.returncode, 0, installed.stderr)

        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "cp936:strict"
        checked = self.run_configurator(
            "--check",
            python_path=Path(sys.executable),
            environment=environment,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertNotIn("UnicodeEncodeError", checked.stderr)
        self.assertIn("待嵌 � 🙂", checked.stdout)

    def test_error_output_survives_cp936_strict_console_output(self) -> None:
        invalid_settings = self.root / "坏 � 🙂" / "settings.json"
        invalid_settings.parent.mkdir()
        invalid_settings.write_text("{", encoding="utf-8")
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "cp936:strict"

        failed = self.run_configurator(
            "--install",
            settings=invalid_settings,
            environment=environment,
        )
        self.assertEqual(failed.returncode, 1)
        self.assertNotIn("UnicodeEncodeError", failed.stderr)
        self.assertIn("坏 � 🙂", failed.stderr)


@unittest.skipUnless(BASH.is_file(), "requires bash")
class BootstrapStatusLineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.kb_home = self.root / "Bootstrap KB Home"
        self.settings = self.root / "Fake Claude Home" / "settings.json"
        self.modules = self.root / "modules"
        self.kb_home.mkdir()
        self.settings.parent.mkdir()
        self.modules.mkdir()
        for module in ("jieba", "cryptography", "yaml"):
            (self.modules / f"{module}.py").write_text("", encoding="utf-8")
        fastembed = self.modules / "fastembed"
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
        (self.kb_home / "kb.db").touch()
        (self.kb_home / "memory.db").touch()

    def bootstrap_env(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["SULDE_KB_HOME"] = to_msys_path(self.kb_home)
        environment["SULDE_CLAUDE_SETTINGS"] = str(self.settings)
        environment["SULDE_HOST_PROVIDER"] = "claude"
        environment["PYTHONPATH"] = str(self.modules)
        return environment

    def run_bootstrap(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(BASH), to_msys_path(BOOTSTRAP), *arguments],
            env=self.bootstrap_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )

    def test_bootstrap_dry_run_reports_plan_without_side_effects(self) -> None:
        shutil.rmtree(self.kb_home)
        result = self.run_bootstrap("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Merge Sulde statusLine", result.stdout)
        self.assertIn("settings write executed in dry-run mode", result.stdout)
        self.assertFalse(self.kb_home.exists())
        self.assertFalse(self.settings.exists())

    def test_bootstrap_wires_config_and_launcher_always_degrades_cleanly(self) -> None:
        original = {"model": "opus", "hooks": {"Stop": [{"command": "keep"}]}}
        self.settings.write_text(json.dumps(original), encoding="utf-8")
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        self.assertIn("statusLine:        已自动接线", result.stdout)
        configured = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual({key: configured[key] for key in original}, original)

        if os.name == "nt":
            venv_python = self.kb_home / "venv" / "Scripts" / "python.exe"
        else:
            venv_python = self.kb_home / "venv" / "bin" / "python"
        launcher = self.kb_home / "bin" / "sulde-statusline.py"
        target = self.root / "fake-status.py"
        environment = os.environ.copy()
        environment["SULDE_STATUS_SCRIPT"] = str(target)

        cases = (
            ('print("normal output")\n', "normal output"),
            ('print("bad"); raise SystemExit(7)\n', "bad"),
            ("pass\n", "sulde 🔴(状态脚本无输出)"),
            ('import time; time.sleep(2)\n', "sulde 🔴(状态脚本异常)"),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                target.write_text(source, encoding="utf-8")
                started = __import__("time").perf_counter()
                launched = subprocess.run(
                    [str(venv_python), str(launcher)],
                    env=environment,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=4,
                    check=False,
                )
                elapsed = __import__("time").perf_counter() - started
                self.assertEqual(launched.returncode, 0, launched.stderr)
                self.assertEqual(launched.stdout.strip(), expected)
                if "sleep" in source:
                    self.assertLess(elapsed, 1.8)

        conflicting = {**original, "statusLine": {"type": "command", "command": "other"}}
        self.settings.write_text(json.dumps(conflicting), encoding="utf-8")
        rerun = self.run_bootstrap()
        self.assertEqual(rerun.returncode, 0, rerun.stderr)
        self.assertIn("warning: statusLine 自动接线失败", rerun.stderr)
        self.assertIn("statusLine:        需手工处理", rerun.stdout)
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8")), conflicting)

    def test_codex_bootstrap_never_touches_claude_settings(self) -> None:
        original = {"model": "opus", "hooks": {"Stop": [{"command": "keep"}]}}
        self.settings.write_text(json.dumps(original), encoding="utf-8")
        result = self.run_bootstrap("--host", "codex")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8")), original)
        self.assertIn("host provider:     codex", result.stdout)
        self.assertIn("不使用 Claude Code settings.json", result.stdout)

    def test_generated_launcher_forces_child_utf8_under_cp936_locale(self) -> None:
        bootstrapped = self.run_bootstrap()
        self.assertEqual(
            bootstrapped.returncode,
            0,
            f"stdout:\n{bootstrapped.stdout}\nstderr:\n{bootstrapped.stderr}",
        )
        if os.name == "nt":
            venv_python = self.kb_home / "venv" / "Scripts" / "python.exe"
        else:
            venv_python = self.kb_home / "venv" / "bin" / "python"
        launcher = self.kb_home / "bin" / "sulde-statusline.py"

        payload = (
            b"\x1b[33m\xe5\xbe\x85\xe5\xb5\x8c "
            b"\xe6\x94\xb6\xe5\x89\xb2 \xe2\x97\x8f\x1b[0m\n"
        )
        target = self.root / "utf8-status.py"
        target.write_text(
            "print('\\x1b[33m待嵌 收割 ●\\x1b[0m')\n",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["SULDE_STATUS_SCRIPT"] = str(target)
        environment["PYTHONIOENCODING"] = "cp936:strict"

        launched = subprocess.run(
            [str(venv_python), str(launcher)],
            env=environment,
            capture_output=True,
            timeout=4,
            check=False,
        )
        self.assertEqual(launched.returncode, 0, launched.stderr)
        self.assertEqual(launched.stdout, payload)
        self.assertIn(bytes.fromhex("e5 be 85 e5 b5 8c"), launched.stdout)
        self.assertIn(bytes.fromhex("e6 94 b6 e5 89 b2"), launched.stdout)
        self.assertNotIn(bytes.fromhex("ef bf bd"), launched.stdout)


if __name__ == "__main__":
    unittest.main()
