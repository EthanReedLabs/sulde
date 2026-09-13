from __future__ import annotations

import importlib.util
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import unittest
import venv
from unittest import mock


ROOT = Path(
    os.environ.get("SULDE_PLUGIN_UNDER_TEST", Path(__file__).resolve().parents[1])
)
CONFIGURATOR = ROOT / "scripts" / "kb" / "configure-global.py"


def load_configurator_module():
    spec = importlib.util.spec_from_file_location("configure_global", CONFIGURATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConfigureGlobalCliTest(unittest.TestCase):
    def test_cache_candidates_prefer_new_name_and_keep_legacy_fallback(self) -> None:
        module = load_configurator_module()
        with tempfile.TemporaryDirectory() as name:
            home = Path(name)
            current = home / ".claude/plugins/cache/sulde/sulde/0.8.4"
            legacy = home / ".claude/plugins/cache/sulde/sulde-cc/0.8.4"
            current.mkdir(parents=True)
            legacy.mkdir(parents=True)
            with mock.patch.object(module.Path, "home", return_value=home):
                candidates = module.root_candidates()
            self.assertIn(current, candidates)
            self.assertIn(legacy, candidates)
            self.assertLess(candidates.index(current), candidates.index(legacy))

    def test_canonical_kb_home_renders_product_wide_launcher(self) -> None:
        module = load_configurator_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            product_home = Path(temp_dir).resolve() / "sulde-home"
            canonical_kb = product_home / "data" / "kb"
            with mock.patch.dict(os.environ, {"SULDE_HOME": str(product_home)}):
                command = module.kb_cli_command(canonical_kb, platform_name="posix")
            self.assertEqual(command, f'"{product_home / "bin" / "kb-index"}"')

    def test_rendered_kb_command_is_executable_with_spaced_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sulde global rules ") as temp_dir:
            # macOS /var → /private/var 符号链接:期望路径须与被测代码的 resolve 口径一致
            temporary = Path(temp_dir).resolve()
            kb_home = temporary / "KB Home with spaces"
            launcher = kb_home / "bin" / "kb-index"
            claude_md = temporary / "Claude Home" / "CLAUDE.md"
            agents_md = temporary / "Codex Home" / "AGENTS.md"
            launcher.parent.mkdir(parents=True)
            launcher.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "print(json.dumps(sys.argv[1:]))\n",
                encoding="utf-8",
            )
            launcher.chmod(0o755)
            if os.name == "nt":
                venv.EnvBuilder(with_pip=False).create(kb_home / "venv")

            installed = subprocess.run(
                [
                    sys.executable,
                    str(CONFIGURATOR),
                    "--install",
                    "--claude-md",
                    str(claude_md),
                    "--agents-md",
                    str(agents_md),
                    "--kb-home",
                    str(kb_home),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)

            command = next(
                line
                for line in agents_md.read_text(encoding="utf-8").splitlines()
                if line.endswith(' search "<症状描述>" -k 5 --json')
            )
            if os.name == "nt":
                expected_prefix = (
                    f'"{kb_home / "venv" / "Scripts" / "python.exe"}" '
                    f'"{launcher}"'
                )
            else:
                expected_prefix = f'"{launcher}"'
            self.assertTrue(command.startswith(expected_prefix), command)
            executed = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
            self.assertEqual(
                executed.returncode,
                0,
                msg=f"command: {command}\nstdout: {executed.stdout}\nstderr: {executed.stderr}",
            )
            self.assertIn('"search"', executed.stdout)

            checked = subprocess.run(
                [
                    sys.executable,
                    str(CONFIGURATOR),
                    "--check",
                    "--claude-md",
                    str(claude_md),
                    "--agents-md",
                    str(agents_md),
                    "--kb-home",
                    str(kb_home),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(checked.stdout.count("rule block OK"), 2)

    def test_posix_shape_stays_direct_and_templates_have_one_cli_placeholder(self) -> None:
        module = load_configurator_module()
        command = module.kb_cli_command(
            PurePosixPath("/tmp/KB Home with spaces"), platform_name="posix"
        )
        expected = Path("/tmp/KB Home with spaces").resolve() / "bin" / "kb-index"
        self.assertEqual(command, f'"{expected}"')

        templates = (
            ROOT / "templates" / "global" / "claude-rules.md",
            ROOT / "templates" / "global" / "codex-agents-rules.md",
        )
        for template in templates:
            source = template.read_text(encoding="utf-8")
            self.assertIn("{KB_CLI}", source)
            self.assertNotIn("{KB_BIN}", source)


if __name__ == "__main__":
    unittest.main()
