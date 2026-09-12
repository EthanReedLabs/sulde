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
import venv


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts" / "kb" / "kb-index"
KB_CLI = ROOT / "hooks" / "lib" / "kb_cli.py"


EXPECTED_COMMANDS = {
    "build": ("tools/kb-index/build.py", ()),
    "search": ("tools/kb-index/search.py", ()),
    "related": ("tools/kb-index/search.py", ("related",)),
    "fleet": ("scripts/kb/fleet.py", ()),
    "mem-init": ("tools/kb-index/memory.py", ("init",)),
    "mem-embed": ("tools/kb-index/memory.py", ("embed-pending",)),
    "mem-search": ("tools/kb-index/memory.py", ("search",)),
    "mem-annotate": ("tools/kb-index/memory.py", ("annotate",)),
    "mem-graph": ("tools/kb-index/memory.py", ("graph",)),
    "mem-recent": ("tools/kb-index/memory.py", ("recent",)),
    "mem-prune": ("tools/kb-index/memory.py", ("prune",)),
}


def create_venv(home: Path) -> Path:
    venv.EnvBuilder(with_pip=False).create(home / "venv")
    return home / "venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )


def minimal_environment(home: Path) -> dict[str, str]:
    empty_path = home / "empty-path"
    empty_path.mkdir(parents=True, exist_ok=True)
    environment = {
        "PATH": str(empty_path),
        "PYTHONDONTWRITEBYTECODE": "1",
        "SULDE_KB_HOME": str(home),
    }
    for name in ("SYSTEMROOT", "WINDIR", "USERPROFILE", "HOME", "TEMP", "TMP"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def create_fixture(base: Path) -> tuple[Path, Path, Path]:
    root = base / "root"
    home = base / "home"
    entry = root / "scripts" / "kb" / "kb-index"
    shared_cli = root / "hooks" / "lib" / "kb_cli.py"
    entry.parent.mkdir(parents=True)
    shared_cli.parent.mkdir(parents=True)
    shutil.copy2(ENTRY, entry)
    shutil.copy2(KB_CLI, shared_cli)

    scripts = {
        "tools/kb-index/build.py": "import json; print(json.dumps({'args': __import__('sys').argv[1:]}))\n",
        "tools/kb-index/search.py": (
            "import json, sys\n"
            "print(json.dumps({'args': sys.argv[1:]}, ensure_ascii=False))\n"
        ),
        "tools/kb-index/memory.py": (
            "import json, sys\n"
            "print(json.dumps({'args': sys.argv[1:]}, ensure_ascii=False))\n"
        ),
        "scripts/kb/fleet.py": "import json; print(json.dumps({'args': __import__('sys').argv[1:]}))\n",
    }
    for relative, source in scripts.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    return entry, home, create_venv(home)


class KbIndexEntryTests(unittest.TestCase):
    def test_all_eleven_commands_match_the_pre_rewrite_mapping(self) -> None:
        namespace = runpy.run_path(str(KB_CLI))
        root = Path("fixture-root")
        home = Path("fixture-home")
        python = home / "venv" / "bin" / "python"

        self.assertEqual(tuple(namespace["command_names"]()), tuple(EXPECTED_COMMANDS))
        for subcommand, (relative, prefix) in EXPECTED_COMMANDS.items():
            with self.subTest(subcommand=subcommand):
                command = namespace["build_command"](
                    root,
                    home,
                    subcommand,
                    ["argument"],
                    python=python,
                )
                self.assertEqual(command[0], str(python))
                self.assertEqual(Path(command[1]), root / relative)
                self.assertEqual(command[2:], [*prefix, "argument"])

    @unittest.skipIf(os.name != "nt", "本用例断言 Windows 的 subprocess 分支;POSIX 由 test_posix_branch 覆盖")
    def test_entry_uses_shared_mapping_without_a_second_target_table(self) -> None:
        source = ENTRY.read_text(encoding="utf-8")
        namespace = runpy.run_path(str(ENTRY))
        python = Path("fixture-home/venv/bin/python")
        built = [str(python), "fixture-target.py", "argument"]

        self.assertNotIn("tools/kb-index/", source)
        self.assertNotIn("_COMMANDS", source)
        with (
            mock.patch.dict(os.environ, {"SULDE_KB_HOME": "fixture-home"}),
            mock.patch.object(
                namespace["kb_cli"], "resolve_venv_python", return_value=python
            ) as resolve,
            mock.patch.object(
                namespace["kb_cli"], "build_command", return_value=built
            ) as build,
            mock.patch.object(
                namespace["subprocess"],
                "run",
                return_value=subprocess.CompletedProcess(built, 0),
            ) as execute,
        ):
            self.assertEqual(namespace["main"](["search", "argument"]), 0)

        resolve.assert_called_once_with(Path("fixture-home"), require_executable=True)
        build.assert_called_once_with(
            namespace["REPO_ROOT"],
            Path("fixture-home"),
            "search",
            ["argument"],
            python=python,
        )
        execute.assert_called_once_with(built, env=mock.ANY, check=False)
        self.assertEqual(execute.call_args.kwargs["env"]["PYTHONIOENCODING"], "utf-8")

    def test_posix_branch_replaces_process_with_the_venv_interpreter(self) -> None:
        namespace = runpy.run_path(str(ENTRY))
        python = Path("fixture-home/venv/bin/python")
        built = [str(python), "fixture-target.py", "argument"]

        class ExecCalled(Exception):
            pass

        with (
            mock.patch.dict(os.environ, {"SULDE_KB_HOME": "fixture-home"}),
            mock.patch.object(namespace["os"], "name", "posix"),
            mock.patch.object(
                namespace["kb_cli"], "resolve_venv_python", return_value=python
            ),
            mock.patch.object(
                namespace["kb_cli"], "build_command", return_value=built
            ),
            mock.patch.object(
                namespace["os"], "execve", side_effect=ExecCalled
            ) as execute,
            self.assertRaises(ExecCalled),
        ):
            namespace["main"](["search", "argument"])

        executable, command, environment = execute.call_args.args
        self.assertEqual(executable, str(python))
        self.assertEqual(command, built)
        self.assertEqual(environment["SULDE_KB_HOME"], "fixture-home")

    def test_minimal_environment_search_and_mem_annotate_need_no_bash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            entry, home, python = create_fixture(Path(temp_dir))
            environment = minimal_environment(home)
            payload = json.dumps({"entities": [], "edges": []}, separators=(",", ":"))
            cases = (
                (["search", "含中文查询", "-k", "1", "--json"], ["含中文查询", "-k", "1", "--json"]),
                (["mem-annotate", payload], ["annotate", payload]),
            )
            for arguments, expected in cases:
                with self.subTest(arguments=arguments):
                    completed = subprocess.run(
                        [str(python), str(entry), *arguments],
                        capture_output=True,
                        env=environment,
                        timeout=20,
                        check=False,
                    )
                    self.assertEqual(
                        completed.returncode,
                        0,
                        completed.stderr.decode("utf-8", errors="replace"),
                    )
                    self.assertEqual(json.loads(completed.stdout)["args"], expected)
                    self.assertEqual(completed.stderr, b"")

    def test_home_returns_before_venv_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "missing-venv-home"
            completed = subprocess.run(
                [sys.executable, str(ENTRY), "home"],
                capture_output=True,
                env=minimal_environment(home),
                timeout=20,
                check=False,
            )

            self.assertEqual(
                completed.returncode,
                0,
                completed.stderr.decode("utf-8", errors="replace"),
            )
            self.assertEqual(completed.stdout.decode("utf-8").splitlines(), [str(home)])
            self.assertEqual(completed.stderr, b"")


if __name__ == "__main__":
    unittest.main()
