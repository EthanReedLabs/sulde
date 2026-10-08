"""Normal-before-injection evidence controls; no production stores or providers."""
from datetime import datetime, timedelta, timezone
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tests import test_test_evidence as evidence_fixtures


class StrictEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.module = evidence_fixtures.load_module()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.now = datetime(2026, 10, 4, tzinfo=timezone.utc)
        self.identity = {"workspace_sha256": "a" * 64, "risk": "small", "tests": ["tests.fixture"],
                         "runner_sha256": "b" * 64}
        self.key = self.module._digest(self.identity)

    def record(self, name="normal", **changes):
        log = self.root / (name + ".log")
        log.write_bytes(b"complete fixture result\n")
        row = {"schema": self.module.SCHEMA, "run_id": name, "evidence_key": self.key,
               "workspace_sha256": self.identity["workspace_sha256"], "risk": "small",
               "tests": self.identity["tests"], "runner_sha256": self.identity["runner_sha256"],
               "input_identity_before": self.identity, "input_identity_after": self.identity,
               "status": "passed", "partial": False, "exit_code": 0,
               "result": {"complete": True, "verdict": "passed", "exit_code": 0},
               "started_at": (self.now - timedelta(hours=2)).isoformat(),
               "ended_at": (self.now - timedelta(hours=1)).isoformat(),
               "expires_at": (self.now + timedelta(days=29)).isoformat(),
               "log": log.name, "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(), **changes}
        (self.root / (name + ".json")).write_text(json.dumps(row), encoding="utf-8")
        return row

    def reuse(self):
        return self.module.reusable_record(self.root, self.key, current=self.now)

    def test_incomplete_evidence_is_a_miss_after_normal_control(self):
        normal = self.record()
        self.assertEqual(self.reuse()["run_id"], "normal")
        for field in ("exit_code", "partial", "result", "input_identity_after", "expires_at"):
            with self.subTest(field=field):
                row = dict(normal)
                del row[field]
                (self.root / "normal.json").write_text(json.dumps(row), encoding="utf-8")
                self.assertIsNone(self.reuse())

    def test_future_expired_naive_and_disagreeing_result_are_misses(self):
        self.record()
        self.assertIsNotNone(self.reuse())
        for changes in (
            {"ended_at": (self.now + timedelta(hours=1)).isoformat()},
            {"expires_at": self.now.isoformat()},
            {"ended_at": "2026-10-03T00:00:00"},
            {"result": {"complete": True, "verdict": "passed", "exit_code": 1}},
            {"input_identity_after": {**self.identity, "workspace_sha256": "c" * 64}},
        ):
            with self.subTest(changes=changes):
                self.record(**changes)
                self.assertIsNone(self.reuse())

    def test_log_bytes_missing_and_escaping_paths_are_misses(self):
        self.record()
        self.assertIsNotNone(self.reuse())
        (self.root / "normal.log").write_bytes(b"corrupted")
        self.assertIsNone(self.reuse())
        self.record(log="../outside.log")
        self.assertIsNone(self.reuse())
        self.record()
        (self.root / "normal.log").rename(self.root / "held.log")
        self.assertIsNone(self.reuse())
        (self.root / "normal.log").symlink_to(self.root / "held.log")
        self.assertIsNone(self.reuse())

    def test_later_failure_vetoes_old_success_until_new_valid_success(self):
        self.record()
        self.assertIsNotNone(self.reuse())
        self.record("failed", status="failed", exit_code=1, ended_at=self.now.isoformat(),
                    result={"complete": True, "verdict": "failed", "exit_code": 1})
        self.assertIsNone(self.reuse())
        self.now += timedelta(hours=2)
        self.record("new-pass")
        self.assertEqual(self.reuse()["run_id"], "new-pass")

    def test_risk_cannot_downgrade_and_unknown_executable_requires_full(self):
        m = self.module
        self.assertEqual(m.classify(["docs/note.md"]), "small")
        self.assertEqual(m.classify(["scripts/release/install_codex_plugin.py"], requested="small"), "refactor")
        self.assertEqual(m.classify(["scripts/kb/unmapped_executable.py"]), "refactor")
        self.assertEqual(m.impacted_tests(["scripts/kb/unmapped_executable.py"], "medium"), [])
        self.assertIn("tests.test_codex_plugin_install",
                      m.impacted_tests(["scripts/release/install_transaction_journal.py"], "medium"))

    def test_unattributable_key_vetoes_green_but_valid_other_key_does_not(self):
        self.record()
        self.assertEqual(self.reuse()["run_id"], "normal")
        other = self.record("new-failure", evidence_key="f" * 64, status="failed", exit_code=1,
                            ended_at=self.now.isoformat(),
                            result={"complete": True, "verdict": "failed", "exit_code": 1})
        self.assertEqual(self.reuse()["run_id"], "normal")
        for value in ("missing", None, "invalid", "g" * 64, "f" * 63, 123):
            with self.subTest(key=value):
                row = dict(other)
                if value == "missing":
                    del row["evidence_key"]
                else:
                    row["evidence_key"] = value
                (self.root / "new-failure.json").write_text(json.dumps(row), encoding="utf-8")
                self.assertTrue(self.reuse() is None, "unattributable failure must veto old green")

    def test_run_plan_real_child_reuse_and_input_drift(self):
        runner = self.root / "runner.py"
        runner.write_text("print('isolated fixture passed')\n", encoding="utf-8")
        selected = {"base": "fixture", "head": "fixture", "risk": "small", "tests": [], "suite": "full"}
        m = self.module
        with mock.patch.object(m, "evidence_root", return_value=self.root / "records"), \
             mock.patch.object(m, "RUNNER", runner), mock.patch.object(m, "clean_source_bytecode", return_value={}), \
             mock.patch.object(m, "_workspace_digest", return_value="a" * 64):
            code, normal = m.run_plan(selected)
            self.assertEqual(code, 0)
            self.assertFalse(normal["reused"])
            code, reused = m.run_plan(selected)
            self.assertEqual(code, 0)
            self.assertTrue(reused["reused"])
            with mock.patch.object(m, "_workspace_digest", side_effect=["a" * 64, "b" * 64]):
                code, drift = m.run_plan(selected, reuse=False)
            self.assertNotEqual(code, 0)
            self.assertNotEqual(drift["status"], "passed")
            self.assertEqual(drift["runner_exit_code"], 0)

    def test_recall_has_explicit_thirty_day_bound_and_can_only_add_tests(self):
        m = self.module
        hints = {"strategy": {"recommended_tests": ["tests.test_test_evidence"], "experience_ids": []}}
        with mock.patch.dict(m.os.environ, {"SULDE_KB_HOME": str(self.root)}), \
             mock.patch.object(m.runpy, "run_path", return_value={"recall": mock.Mock(return_value=hints)}) as loader:
            m.experience_test_hints(["scripts/kb/self-repair.py"])
            recall = loader.return_value["recall"]
            self.assertEqual(recall.call_args.kwargs["ttl_seconds"], 30 * 86400)
        with mock.patch.object(m, "experience_test_hints", return_value=hints), \
             mock.patch.object(m, "changed_paths", return_value=["scripts/kb/self-repair.py"]), \
             mock.patch.object(m, "_git", return_value="a" * 40):
            selected = m.plan("dev")
            self.assertIn("tests.test_self_repair", selected["tests"])
            self.assertIn("tests.test_life_cycle", selected["tests"])
            self.assertIn("tests.test_test_evidence", selected["tests"])

    def test_real_git_paths_preserve_spaces_unicode_and_rename_sources(self):
        repository = self.root / "path-fixture"
        repository.mkdir()
        def git(*args):
            return subprocess.run(["git", "-C", str(repository), *args], check=True,
                                  capture_output=True, text=True, encoding="utf-8", errors="replace")
        git("init")
        (repository / "scripts").mkdir()
        for name in ("old name.py", "unstaged 中文.py"):
            (repository / "scripts" / name).write_text("pass\n", encoding="utf-8")
        git("add", ".")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-m", "fixture")
        git("mv", "scripts/old name.py", "scripts/new name.py")
        (repository / "scripts/unstaged 中文.py").write_text("pass\npass\n", encoding="utf-8")
        (repository / "scripts/untracked 中文.py").write_text("pass\n", encoding="utf-8")
        with mock.patch.object(self.module, "ROOT", repository):
            changed = self.module.changed_paths("HEAD")
            self.assertEqual(set(changed), {"scripts/old name.py", "scripts/new name.py",
                             "scripts/unstaged 中文.py", "scripts/untracked 中文.py"})
            self.assertEqual(self.module.classify(changed), "refactor")
            git("add", ".")
            git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "-c", "commit.gpgsign=false", "commit", "-m", "fixture changes")
            self.assertEqual(self.module.changed_paths("HEAD~1"), changed)

    def test_interrupted_attempt_and_corrupt_record_veto_prior_green(self):
        m = self.module
        runner = self.root / "crash-runner.py"
        runner.write_text("print('control passes')\n", encoding="utf-8")
        selected = {"base": "fixture", "head": "fixture", "risk": "small", "tests": [], "suite": "full"}
        for failure in ("launch", "interrupt", "preprocess", "postprocess", "terminal_write", "corrupt"):
            with self.subTest(failure=failure):
                root = self.root / failure
                with mock.patch.object(m, "evidence_root", return_value=root), \
                     mock.patch.object(m, "RUNNER", runner), \
                     mock.patch.object(m, "clean_source_bytecode", return_value={}), \
                     mock.patch.object(m, "_workspace_digest", return_value="a" * 64):
                    code, normal = m.run_plan(selected, reuse=False)
                    self.assertEqual(code, 0)
                    self.assertIsNotNone(m.reusable_record(root, normal["evidence_key"], current=m._now()))
                    if failure == "corrupt":
                        (root / "interrupted.json").write_text("{partial", encoding="utf-8")
                    elif failure in {"preprocess", "postprocess"}:
                        effects = [OSError("preprocess")] if failure == "preprocess" else [{}, OSError("postprocess")]
                        with mock.patch.object(m, "clean_source_bytecode", side_effect=effects):
                            with self.assertRaises(OSError):
                                m.run_plan(selected, reuse=False)
                    elif failure == "terminal_write":
                        original = m._atomic_record
                        def interrupted_publish(path, record):
                            original(path, record)
                            if record["status"] != "pending":
                                raise OSError("terminal publication failure")
                        with mock.patch.object(m, "_atomic_record", side_effect=interrupted_publish):
                            with self.assertRaises(OSError):
                                m.run_plan(selected, reuse=False)
                    else:
                        error = OSError("launch") if failure == "launch" else KeyboardInterrupt()
                        with mock.patch.object(m.subprocess, "run", side_effect=error):
                            with self.assertRaises(type(error)):
                                m.run_plan(selected, reuse=False)
                    self.assertIsNone(m.reusable_record(root, normal["evidence_key"], current=m._now()))

    def test_actual_plan_cli_uses_local_home_and_cannot_reduce_risk(self):
        repository = self.root / "repository"
        script = repository / "scripts/kb/test-evidence.py"
        script.parent.mkdir(parents=True)
        script.write_bytes(evidence_fixtures.SCRIPT.read_bytes())
        environment = {**self.module.os.environ, "SULDE_KB_HOME": str(self.root),
                       "SULDE_TEST_EVIDENCE_HOME": str(self.root / "evidence")}
        for arguments in (("init",), ("add", "."),
                          ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                           "-c", "commit.gpgsign=false", "commit", "-m", "local fixture")):
            subprocess.run(["git", "-C", str(repository), *arguments], check=True,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        (repository / "scripts/new-unknown.py").write_text("pass\n", encoding="utf-8")
        result = subprocess.run([self.module.sys.executable, "-B", str(script),
                                 "plan", "--base", "HEAD", "--risk", "small"],
                                cwd=repository, env=environment, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        selected = json.loads(result.stdout)
        self.assertEqual(selected["risk"], "refactor")
        self.assertFalse((self.root / "evidence").exists())

    def test_environment_changes_invalidate_without_recording_secret_values(self):
        m = self.module
        selected = {"risk": "small", "tests": []}
        with mock.patch.object(m, "_workspace_digest", return_value="a" * 64):
            with mock.patch.dict(m.os.environ, {"S2_TEST_OPTION": "first"}):
                first = m.evidence_key(selected)
            with mock.patch.dict(m.os.environ, {"S2_TEST_OPTION": "second"}):
                second = m.evidence_key(selected)
            self.assertNotEqual(first, second)
            with mock.patch.dict(m.os.environ, {"S2_SECRET_TOKEN": "private-fixture"}):
                identity = m.input_identity(selected)
            with mock.patch.dict(m.os.environ, {"S2_SECRET_TOKEN": "different-private-fixture"}):
                changed = m.input_identity(selected)
            self.assertNotEqual(identity["environment_sha256"], changed["environment_sha256"])
            self.assertNotIn("private-fixture", json.dumps(identity))

    def test_cli_and_life_share_explicit_or_default_evidence_root(self):
        m = self.module
        home = self.root.resolve() / "data" / "kb"
        with mock.patch.dict(m.os.environ, {"SULDE_KB_HOME": str(home)}, clear=True):
            self.assertEqual(m.evidence_root(), home.parent / "test-evidence")
            self.assertEqual(m.evidence_root(home), m.evidence_root())
            with mock.patch.dict(m.os.environ, {"SULDE_TEST_EVIDENCE_HOME": str(self.root / "override")}):
                self.assertEqual(m.evidence_root(home), self.root.resolve() / "override")
                self.assertEqual(m.evidence_root(), m.evidence_root(home))
        with mock.patch.dict(m.os.environ, {"SULDE_HOME": str(self.root)}, clear=True):
            self.assertEqual(m.evidence_root(), self.root.resolve() / "data" / "test-evidence")


class InstallerCollectionTests(unittest.TestCase):
    def test_unregistered_fixture_body_and_skip_drift_still_fail(self):
        path = evidence_fixtures.ROOT / "tests/test_codex_plugin_install.py"
        original_read = Path.read_text
        source = path.read_text(encoding="utf-8")
        for mutation in ("method", "helper", "skip"):
            with self.subTest(mutation=mutation):
                tree = ast.parse(source)
                classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
                if mutation == "skip":
                    classes["CodexPluginInstallTests"].decorator_list = []
                else:
                    owner = classes["CodexPluginInstallFixture" if mutation == "helper" else "CodexPluginInstallTests"]
                    method = next(n for n in owner.body if isinstance(n, ast.FunctionDef))
                    method.body.append(ast.Pass())
                changed = ast.unparse(ast.fix_missing_locations(tree))
                def read(candidate, *args, **kwargs):
                    return changed if candidate == path else original_read(candidate, *args, **kwargs)
                with mock.patch.object(Path, "read_text", read):
                    with self.assertRaises(AssertionError):
                        self.test_fixture_extraction_preserves_all_original_bodies_and_skip_conditions()

    def test_fixture_extraction_preserves_all_original_bodies_and_skip_conditions(self):
        path = evidence_fixtures.ROOT / "tests/test_codex_plugin_install.py"
        frozen = json.loads((evidence_fixtures.ROOT / "tests/fixtures/guardian_s2_installer_ast.json").read_text(encoding="utf-8"))
        new = ast.parse(path.read_text(encoding="utf-8"))
        digest = lambda node: hashlib.sha256(ast.dump(node).encode("utf-8")).hexdigest()
        classes = lambda tree: {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
        old_classes, new_classes = frozen["methods"], classes(new)
        old_methods = {(owner, name): checksum for owner, methods in old_classes.items()
                       for name, checksum in methods.items()}
        # Preserve the original extraction snapshot; authorize only explicit,
        # reviewed before/after AST transitions instead of regenerating it.
        evolution = json.loads((evidence_fixtures.ROOT / "tests/fixtures/guardian_s2_installer_ast_evolution.json").read_text(encoding="utf-8"))
        self.assertEqual(evolution["schema"], "sulde-installer-fixture-evolution-v1")
        expected_methods, expected_helpers = dict(old_methods), dict(frozen["helpers"])
        seen = set()
        for change in evolution["changes"]:
            identity = (change["kind"], change["owner"], change["name"])
            self.assertNotIn(identity, seen)
            seen.add(identity)
            self.assertTrue(change["commit"] and change["reason"])
            self.assertRegex(change["after_sha256"], r"^[0-9a-f]{64}$")
            if change["kind"] == "helper":
                self.assertEqual(change["owner"], "CodexPluginInstallFixture")
                target, key = expected_helpers, change["name"]
            else:
                self.assertEqual(change["kind"], "method")
                target, key = expected_methods, (change["owner"], change["name"])
            self.assertIn(key, target)
            self.assertEqual(target[key], change["before_sha256"])
            target[key] = change["after_sha256"]
        new_methods = {(c.name, n.name): digest(n) for c in new_classes.values()
                       for n in c.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")}
        self.assertEqual(len(old_methods), 62)
        self.assertEqual(expected_methods, new_methods)
        fixture = new_classes["CodexPluginInstallFixture"]
        self.assertEqual(frozen["helper_order"], [n.name for n in fixture.body if isinstance(n, ast.FunctionDef)])
        self.assertEqual(expected_helpers, {n.name: digest(n) for n in fixture.body if isinstance(n, ast.FunctionDef)})
        self.assertEqual(fixture.bases, [])
        old_skip = frozen["skip"]
        for name in old_classes:
            self.assertEqual([digest(n) for n in new_classes[name].decorator_list], old_skip)
        from tests import test_codex_plugin_install as module
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        cases = [case for group in suite for case in group]
        self.assertEqual(len(cases), 62)
        self.assertEqual(len({case.id() for case in cases}), 62)
        base_names = {name for owner, name in old_methods if owner == "CodexPluginInstallTests"}
        removed = {(owner, name): ("CodexPluginInstallTests", name)
                   for owner in old_classes if owner != "CodexPluginInstallTests" for name in base_names}
        self.assertEqual(len(removed), 108)
        for old_id, retained_id in removed.items():
            self.assertNotIn(old_id, new_methods)
            self.assertEqual(expected_methods[retained_id], new_methods[retained_id])
        for case in cases:
            for name in ("setUp", "tearDown", "run_installer", "prepare_artifact"):
                self.assertIs(getattr(type(case), name), getattr(module.CodexPluginInstallFixture, name))


if __name__ == "__main__":
    unittest.main()
