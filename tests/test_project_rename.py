from __future__ import annotations

import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProjectRenameTests(unittest.TestCase):
    def test_meta_work_recognizes_both_names_without_matching_other_projects(self):
        is_meta = runpy.run_path(str(ROOT / "scripts/kb/calibrate.py"))["is_meta_work"]
        for path in ("/work/sulde", "/work/sulde-cc/scripts", "C:\\work\\sulde\\scripts"):
            self.assertTrue(is_meta(path), path)
        for path in ("/work/sulde-client", "/work/not-sulde", "/work/app", None):
            self.assertFalse(is_meta(path), path)

    @unittest.skipUnless(shutil.which("bash") and shutil.which("git"), "Bash and Git required")
    def test_frontend_installers_discover_new_and_legacy_plugin_ids(self):
        for stack in ("android", "ios", "flutter", "harmony"):
            for plugin_name in ("sulde", "sulde-cc"):
                with self.subTest(stack=stack, plugin_name=plugin_name):
                    with tempfile.TemporaryDirectory(prefix="sulde rename ") as name:
                        base = Path(name).resolve()
                        frontend = base / "frontend"
                        scripts = frontend / "scripts"
                        scripts.mkdir(parents=True)
                        installer = scripts / "pre-commit-installer.sh"
                        shutil.copy2(ROOT / "template" / stack / "scripts/pre-commit-installer.sh", installer)
                        subprocess.run(["git", "init", "-q", str(frontend)], check=True)
                        home = base / "home"
                        hooks = home / ".claude/plugins/cache/sulde" / plugin_name / "0.8.4/hooks/git-precommit"
                        hooks.mkdir(parents=True)
                        environment = dict(os.environ)
                        environment["HOME"] = str(home)
                        environment.pop("CLAUDE_PLUGIN_ROOT", None)
                        completed = subprocess.run(
                            ["bash", str(installer)], cwd=frontend, env=environment,
                            capture_output=True, text=True, check=False,
                        )
                        self.assertEqual(completed.returncode, 0, completed.stderr)
                        generated = frontend / ".git/hooks/pre-commit"
                        self.assertIn(str(hooks), generated.read_text())
                        self.assertTrue(os.access(generated, os.X_OK))
