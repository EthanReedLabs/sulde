from __future__ import annotations

import importlib.util
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "export_public_harness", ROOT / "scripts/release/export_public_harness.py")
export = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export)


class PublicHarnessExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sulde-public-export-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        self.public = self.root / "public"
        self.source_revision = self.repository(self.source, {
            "scripts/kb/memory.py": "# Synthetic engine, no real memory.\n",
            "scripts/kb/intent_guardian.py": "# Synthetic Guardian implementation.\n",
            "scripts/kb/life-cycle.py": "# Synthetic LIFE implementation.\n",
            "tools/kb-index/search.py": "# Synthetic search implementation.\n",
            "integrations/codex/plugins/sulde/scripts/pre-tool-use.py": "# Synthetic adapter.\n",
            "templates/knowledge/schema.json": '{"synthetic_schema": true}\n',
            "spec/task-contract.md": "# Synthetic distribution contract\n",
            "spec/task-authoring.md": "# Synthetic authoring instructions\n",
            "template/_project/docs-hub/00_shared-rules/task-brief.md.template": "# Synthetic brief\n",
            "tests/synthetic_sedimentation.py": "# Independently constructed fixtures\n",
            "knowledge/MANIFEST.json": '{"private_document_title": "PRIVATE_CORPUS_SENTINEL"}',
            "knowledge/work-model/private.md": "PRIVATE_CORPUS_SENTINEL",
            ".sulde/data/memory.json": "PRIVATE_MEMORY_SENTINEL",
            ".ua/knowledge-graph.json": "PRIVATE_GRAPH_SENTINEL",
            "tools/kb-index/golden-mem.jsonl": "PRIVATE_GOLDEN_SENTINEL",
            "tests/fixtures/production.json": "PRIVATE_LEDGER_SENTINEL",
            "scripts/kb/data/receipt.json": "PRIVATE_RECEIPT_SENTINEL",
            "docs/internal-task/REPORT.md": "PRIVATE_REPORT_SENTINEL",
            "scripts/kb/.env.secret": "PRIVATE_SECRET_SENTINEL",
            "LICENSE": "PRIVATE LICENSE DO NOT USE",
            "tests/test_engine.py": "# Synthetic unit test.\n",
        })
        self.public_revision = self.repository(self.public, {
            "LICENSE": "Keep this public license byte-for-byte.\n",
            "README.md": "# Public baseline\n",
            ".gitignore": "__pycache__/\n",
            "bin/sulde": "#!/bin/sh\nexit 0\n",
            "docs/GETTING_STARTED.md": "Already public guide.\n",
            "scripts/sulde.py": "# Public-only standalone CLI.\n",
        })

    @staticmethod
    def command(root, *args):
        return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)

    def repository(self, root, files):
        root.mkdir()
        self.command(root, "init", "-q")
        for name, text in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        if (root / "bin/sulde").exists():
            (root / "bin/sulde").chmod(0o755)
        return self.commit(root)

    def commit(self, root):
        self.command(root, "add", "--all")
        self.command(root, "-c", "user.name=Synthetic Test", "-c", "user.email=test@example.invalid",
                     "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                     "commit", "-qm", "Synthetic fixture")
        return self.command(root, "rev-parse", "HEAD").decode().strip()

    def plan(self):
        return export.build_plan(self.source, self.source_revision, self.public, self.public_revision)

    def test_includes_implementation_but_not_formal_data_anywhere(self):
        plan, files = self.plan()
        self.assertIn("scripts/kb/memory.py", files)
        self.assertIn("scripts/kb/intent_guardian.py", files)
        self.assertIn("scripts/kb/life-cycle.py", files)
        self.assertIn("tools/kb-index/search.py", files)
        self.assertIn("templates/knowledge/schema.json", files)
        self.assertIn("spec/task-contract.md", files)
        self.assertIn("spec/task-authoring.md", files)
        self.assertIn("template/_project/docs-hub/00_shared-rules/task-brief.md.template", files)
        self.assertIn("tests/synthetic_sedimentation.py", files)
        self.assertIn("integrations/codex/plugins/sulde/scripts/pre-tool-use.py", files)
        self.assertNotIn(b"PRIVATE_", b"\n".join(files.values()))
        self.assertEqual(json.loads(files["knowledge/MANIFEST.json"])["document_count"], 0)
        self.assertFalse(plan["release_ready"])
        self.assertTrue(plan["review_only"])

    def test_explicit_metadata_adaptation_preserves_portable_consumers(self):
        for path in sorted(export.PUBLIC_METADATA_FILES):
            with self.subTest(path=path):
                original = (ROOT / path).read_bytes()
                rendered = export.public_machine_metadata(path, original)
                self.assertNotIn(b"/Users/eric/", rendered)
                self.assertNotIn(b"sulde-cc-pro", rendered)
                if path.endswith("install-agents.sh"):
                    for token in (b"__SULDE_SOURCE_ROOT__", b"__SULDE_KB_HOME__",
                                  b"__SULDE_CODEX_SESSIONS__", b"__SULDE_USER_BIN__"):
                        self.assertIn(token, rendered)
                if path.endswith("codex-harvest.plist"):
                    self.assertIn(b"__SULDE_CODEX_SESSIONS__", rendered)
                if path.endswith("test_stage_plugin.py"):
                    self.assertIn(b"forbidden = str(ROOT.resolve())", rendered)
                self.assertEqual((ROOT / path).read_bytes(), original)

    def test_unknown_metadata_and_embedded_operational_records_require_review(self):
        with self.assertRaises(export.ExportError):
            export.public_machine_metadata("scripts/kb/install-agents.sh", b"new unreviewed mapping\n")
        with self.assertRaises(export.ExportError):
            export.public_machine_metadata("docs/kb-retrieval-contract.md", b"sulde-cc-pro /Users/eric/unreviewed")
        rows = export.review_content("tests/test_synthetic.py", b'ROW = {"at": "2000-01-01", "run_id": "synthetic"}\n')
        self.assertIn("embedded-operational-record-review", {row["kind"] for row in rows})

    def test_repository_rename_uses_only_exact_reviewed_metadata_urls(self):
        path = "integrations/codex/plugins/sulde/.codex-plugin/plugin.json"
        for name in ("sulde-cc-pro", "sulde-pro"):
            with self.subTest(name=name):
                url = "https://github.com/EthanReedLabs/" + name
                raw = json.dumps({"homepage": url, "repository": url, "name": "sulde"}).encode()
                result = json.loads(export.public_machine_metadata(path, raw))
                self.assertEqual(result, {
                    "homepage": "https://github.com/EthanReedLabs/sulde-cc",
                    "repository": "https://github.com/EthanReedLabs/sulde-cc", "name": "sulde",
                })
        for bad in ("https://github.com/unknown/sulde-pro",
                    "https://github.com/EthanReedLabs/sulde-pro-extra", None):
            with self.subTest(bad=bad), self.assertRaises(export.ExportError):
                export.public_machine_metadata(path, json.dumps({
                    "homepage": bad, "repository": "https://github.com/EthanReedLabs/sulde-pro",
                }).encode())
        for name in ("sulde-cc-pro", "sulde-pro"):
            findings = export.review_content("unreviewed.txt", name.encode())
            self.assertIn("private-repository-name", {row["kind"] for row in findings})

    def test_public_composition_has_real_cases_without_private_report_inputs(self):
        original = (ROOT / "tests/test_r2_guardian_integration.py").read_bytes()
        rendered = export.public_composition_test(original)
        self.assertNotIn(b"guardian-r2-program", rendered)
        self.assertNotIn(b"replay-cases.json", rendered)
        self.assertNotIn(b"base_commit", rendered)
        self.assertIn(b"suite.run(result)", rendered)
        self.assertIn(b"self.assertEqual(result.skipped, [])", rendered)
        with self.assertRaises(export.ExportError):
            export.public_composition_test(b"COMPOSITION_CASES = ('test_fake',)\n")

    def test_runtime_ledger_is_generated_not_copied_from_observed_records(self):
        original = (ROOT / "tests/test_agent_runtime.py").read_bytes()
        rendered = export.public_runtime_fixture(original)
        self.assertNotIn(b"run-1c18f868428c471e959e751a", rendered)
        self.assertNotIn(b"2026-08-27T13:25:31", rendered)
        self.assertNotIn(b"cec437d7a1d35307c90f2ceb9d333de7e556fa685c559010221e39e48fc6a62e", rendered)
        self.assertIn(b"test_synthetic_interruption_runtime_to_production_broker_round_trip", rendered)
        self.assertIn(b"test_h06h_hostile_runtime_and_broker_variants_fail_closed", rendered)
        compile(rendered, "synthetic-public-runtime-test.py", "exec")
        self.assertEqual((ROOT / "tests/test_agent_runtime.py").read_bytes(), original)
        with self.assertRaises(export.ExportError):
            export.public_runtime_fixture(b"H06H_RUN_LEDGER = b'no real fixture'\n")

    def test_runtime_task_privacy_keeps_all_test_methods_and_independent_inputs(self):
        original = (ROOT / "tests/test_agent_runtime.py").read_bytes()
        rendered = export.public_runtime_fixture(original)
        for private in (
            b"run_h06i_fresh_clone_gate", b"10ad8d876d74fe5c4dea8e3b1cc27e178078bdc2",
            b"8f4aef4481a060cc9561434087a24c4cf26307f87755723c9d55a759b21b1db7",
            b"ebd9c2ed27fba48f314bed1584c27f95cc69b9d0",
            b"2f4593090e13aacdde9fab2f74927d48e77cd85d",
            "建立持久审计 cursor、测试隔离和受管任务证据边界".encode(),
            b"T23-runtime-host-parity-r121", b"T04-audit-isolation",
        ):
            self.assertNotIn(private, rendered)
        def tests(raw):
            return {node.name for node in ast.walk(ast.parse(raw))
                    if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")}
        expected = tests(original)
        expected.remove("test_frozen_h06h_bytes_runtime_to_production_broker_round_trip")
        expected.remove("test_historical_t04_schema_is_separate_from_current_execution_authority")
        expected.update({"test_synthetic_interruption_runtime_to_production_broker_round_trip",
                         "test_synthetic_legacy_schema_is_separate_from_current_execution_authority"})
        self.assertEqual(tests(rendered), expected)
        assignments = {node.targets[0].id: node.value for node in ast.parse(rendered).body
                       if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}
        legacy = ast.literal_eval(assignments["SYNTHETIC_LEGACY_TASK_V1"])
        self.assertEqual(legacy["base_commit"], "1" * 40)
        self.assertEqual(legacy["task_id"], "synthetic-legacy-task")
        self.assertEqual(ast.literal_eval(assignments["SYNTHETIC_CURRENT_BASE_COMMIT"]), "2" * 40)
        self.assertIn(b"base commit does not match worktree HEAD", rendered)
        self.assertEqual((ROOT / "tests/test_agent_runtime.py").read_bytes(), original)

    def test_private_task_projection_refuses_missing_input_or_new_helper_consumer(self):
        original = (ROOT / "tests/test_agent_runtime.py").read_bytes()
        with self.assertRaisesRegex(export.ExportError, "inventory drifted"):
            export.public_runtime_task_fixture(original.replace(b"REPAIR6_BRIEF_SHA256", b"MOVED_BRIEF"))
        with self.assertRaisesRegex(export.ExportError, "acquired a consumer"):
            export.public_runtime_task_fixture(original + b"\nrun_h06i_fresh_clone_gate()\n")

    def test_preserves_public_license_cli_guides_and_modes(self):
        plan, files = self.plan()
        self.assertEqual(files["LICENSE"], (self.public / "LICENSE").read_bytes())
        self.assertIn("scripts/sulde.py", files)
        self.assertIn("docs/GETTING_STARTED.md", files)
        record = next(item for item in plan["files"] if item["path"] == "bin/sulde")
        self.assertEqual(record["mode"], "100755")

    def test_public_scaffold_readmes_survive_without_admitting_private_task_data(self):
        path = "template/android/.ai-workspace/session-resume/README.md"
        for root, value in ((self.public, "Public scaffold instructions\n"),
                            (self.source, "PRIVATE_TASK_SENTINEL\n")):
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(value)
        for extra in ("template/android/.ai-workspace/session-resume/actual-task.md",
                      ".ai-workspace/session-resume/README.md"):
            target = self.source / extra
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("PRIVATE_TASK_SENTINEL\n")
        self.public_revision = self.commit(self.public)
        self.source_revision = self.commit(self.source)
        plan, files = self.plan()
        self.assertEqual(len(export.PUBLIC_SCAFFOLD_READMES), 28)
        self.assertEqual(files[path], b"Public scaffold instructions\n")
        self.assertEqual(next(row["origin"] for row in plan["files"] if row["path"] == path), "public")
        self.assertFalse(any(b"PRIVATE_TASK_SENTINEL" in value for value in files.values()))
        self.assertTrue(any(row["path"] == path and row["origin"] == "source" for row in plan["excluded"]))

    def test_operator_projection_removes_state_without_changing_executable_logic(self):
        path = "scripts/kb/governance-report.py"
        original = (ROOT / path).read_bytes()
        rendered = export.public_operator_state(path, original)
        before, after = ast.parse(original), ast.parse(rendered)
        for tree in (before, after):
            for node in tree.body:
                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "DECISION_TRACE":
                    node.value = ast.Constant(value="independent comparison placeholder")
        self.assertEqual(ast.dump(before), ast.dump(after))
        self.assertNotIn("通过(eric)".encode(), rendered)
        self.assertIn("本分发不包含历史提案处置记录".encode(), rendered)
        self.assertEqual((ROOT / path).read_bytes(), original)
        with self.assertRaises(export.ExportError):
            export.public_operator_state(path, b"OTHER_TRACE = 'unknown'\n")

    def test_public_self_is_uninitialized_and_preserves_authority_rules(self):
        path = "templates/SELF.md"
        original = (ROOT / path).read_bytes()
        rendered = export.public_operator_state(path, original)
        self.assertNotIn("eric 的".encode(), rendered)
        self.assertNotIn("golden-mem 五红转绿".encode(), rendered)
        self.assertEqual(rendered.count("未初始化；以本地验收记录为准".encode()), 4)
        for heading, end in (("## 我能自主做什么", "## 目标栈"), ("## 观察清单", None)):
            def section(raw):
                text = raw.decode().split(heading, 1)[1]
                return text.split(end, 1)[0] if end else text
            self.assertEqual(section(original), section(rendered))
        self.assertEqual((ROOT / path).read_bytes(), original)
        with self.assertRaises(export.ExportError):
            export.public_operator_state(path, original.replace("## 目标栈".encode(), b"moved"))

    def test_public_readme_dependency_links_resolve_and_preserve_test_limits(self):
        text = (ROOT / export.OVERLAY_PREFIX / "README.md").read_text()
        for path in ("hooks/requirements.txt", "scripts/kb/bootstrap.sh"):
            self.assertIn(path, text)
            self.assertTrue((ROOT / path).is_file())
        self.assertNotIn("scripts/kb/requirements.txt", text)
        self.assertIn("must not be reported as a pass", text)

    def test_uncommitted_changes_and_untracked_secrets_cannot_enter_snapshot(self):
        first, original = self.plan()
        (self.source / "scripts/kb/memory.py").write_text("UNCOMMITTED_SECRET")
        (self.source / "scripts/kb/local-secret.py").write_text("UNTRACKED_SECRET")
        second, files = self.plan()
        self.assertEqual(first, second)
        self.assertEqual(original, files)

    def test_immutable_revision_cannot_be_replaced_by_branch_or_short_hash(self):
        for value in ("HEAD", "dev", self.source_revision[:7], "--all"):
            with self.subTest(value=value), self.assertRaises(export.ExportError):
                export.snapshot(self.source, value)

    def test_selected_git_symlink_is_rejected_not_followed(self):
        (self.source / "scripts/kb/alias.py").symlink_to("../../knowledge/work-model/private.md")
        self.source_revision = self.commit(self.source)
        with self.assertRaisesRegex(export.ExportError, "symlink"):
            self.plan()

    def test_relative_paths_reject_aliases_and_nonportable_names(self):
        for value in ("../secret", "/tmp/secret", "scripts//a.py", "scripts/./a.py",
                      "scripts/../a.py", "scripts\\a.py", "scripts/A:stream", "scripts/a. ",
                      "scripts/CON.txt", "scripts/a\nb.py", "scripts/cafe\u0301.py"):
            with self.subTest(value=value), self.assertRaises(export.ExportError):
                export.safe_path(value)

    def test_findings_do_not_echo_private_content(self):
        value = b"/Users/private-person/project\n-----BEGIN PRIVATE KEY-----\n"
        findings = export.review_content("scripts/example.py", value)
        self.assertEqual({item["kind"] for item in findings}, {"absolute-user-path", "private-key-material"})
        self.assertNotIn("private-person", json.dumps(findings))
        self.assertNotIn("PRIVATE KEY", json.dumps(findings))

    def test_stages_only_new_private_tree_without_git_or_provenance(self):
        plan, files = self.plan()
        output = self.root / "candidate"
        before_source = self.command(self.source, "status", "--porcelain")
        before_public = self.command(self.public, "status", "--porcelain")
        export.stage_review(output, plan, files)
        export.verify_tree(output / "tree", plan)
        self.assertFalse((output / "INCOMPLETE").exists())
        self.assertTrue((output / "REVIEW_ONLY").exists())
        self.assertFalse((output / "tree/.git").exists())
        self.assertFalse((output / "tree/review.json").exists())
        self.assertEqual(before_source, self.command(self.source, "status", "--porcelain"))
        self.assertEqual(before_public, self.command(self.public, "status", "--porcelain"))
        with self.assertRaisesRegex(export.ExportError, "must not exist"):
            export.stage_review(output, plan, files)

    def test_manifest_or_payload_tamper_fails_before_output_creation(self):
        plan, files = self.plan()
        output = self.root / "candidate"
        plan["release_ready"] = True
        with self.assertRaisesRegex(export.ExportError, "manifest digest"):
            export.stage_review(output, plan, files)
        self.assertFalse(output.exists())
        plan, files = self.plan()
        files["README.md"] = b"changed"
        with self.assertRaisesRegex(export.ExportError, "payload digest"):
            export.stage_review(output, plan, files)
        self.assertFalse(output.exists())

    def test_output_symlink_is_rejected(self):
        plan, files = self.plan()
        (self.root / "alias").symlink_to(self.public, target_is_directory=True)
        with self.assertRaisesRegex(export.ExportError, "symlink"):
            export.stage_review(self.root / "alias/candidate", plan, files)
        self.assertFalse((self.public / "candidate").exists())

    def test_extra_memory_payload_or_changed_content_is_detected_on_readback(self):
        plan, files = self.plan()
        output = self.root / "candidate"
        export.stage_review(output, plan, files)
        (output / "tree/memory.db").write_bytes(b"synthetic data")
        with self.assertRaisesRegex(export.ExportError, "inventory/content"):
            export.verify_tree(output / "tree", plan)

    def test_empty_manifest_loads_using_real_corpus_loader(self):
        sys.path.insert(0, str(ROOT / "tools/kb-index"))
        self.addCleanup(sys.path.remove, str(ROOT / "tools/kb-index"))
        from corpus_manifest import load_manifest
        plan, files = self.plan()
        output = self.root / "candidate"
        export.stage_review(output, plan, files)
        manifest = load_manifest(output / "tree")
        self.assertEqual(manifest.documents, ())
        self.assertEqual(manifest.document_count, 0)
        self.assertEqual(manifest.corpus_sha256, export.digest(b""))

    def test_hook_projection_preserves_all_events_matchers_and_order(self):
        document = {"hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command":
                'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/' + script + '"'}
                for script in ("canon_inject.py", "session_start.py")]}],
            "PreToolUse": [{"matcher": ".*", "hooks": [{"type": "command", "command":
                'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/pre_tool_use.py"', "timeout": 8}]}],
        }}
        projected = json.loads(export.public_hook_manifest(json.dumps(document).encode()))
        self.assertEqual(set(projected["hooks"]), set(document["hooks"]))
        start = projected["hooks"]["SessionStart"][0]["hooks"]
        self.assertEqual([item["command"].split()[-1] for item in start], ["canon_inject.py", "session_start.py"])
        pre = projected["hooks"]["PreToolUse"][0]
        self.assertEqual(pre["matcher"], ".*")
        self.assertEqual(pre["hooks"][0]["timeout"], 8)
        self.assertEqual(pre["hooks"][0]["shell"], "bash")

    def test_unknown_hook_projection_fails_closed(self):
        for command in ('python3 "${CLAUDE_PLUGIN_ROOT}/hooks/unknown.py"',
                        'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/pre_tool_use.py"; echo surprise'):
            document = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": command}]}]}}
            with self.assertRaises(export.ExportError):
                export.public_hook_manifest(json.dumps(document).encode())

    def test_public_version_comes_from_source_manifest(self):
        generated = export.generated_files({"VERSION": b"0.1.0"}, {
            ".claude-plugin/plugin.json": b'{"version": "0.8.4"}'})
        self.assertEqual(generated["VERSION"], b"0.8.4\n")

    def test_synthetic_replacement_preserves_mode_and_records_input_hash(self):
        path = self.source / "scripts/kb/graph-audit.py"
        original = b'#!/usr/bin/env python3\nEXAMPLE = "Apollo"\n'
        path.write_bytes(original)
        path.chmod(0o755)
        self.source_revision = self.commit(self.source)
        plan, files = self.plan()
        self.assertNotIn(b"Apollo", files["scripts/kb/graph-audit.py"])
        self.assertIn(b"SyntheticApplication", files["scripts/kb/graph-audit.py"])
        entry = next(item for item in plan["files"] if item["path"] == "scripts/kb/graph-audit.py")
        self.assertEqual(entry["mode"], "100755")
        audit = next(item for item in plan["transformations"] if item["path"] == entry["path"])
        self.assertEqual(audit["input_sha256"], export.digest(original))
        self.assertEqual(audit["output_sha256"], entry["sha256"])

    def test_public_test_adaptation_requires_exact_old_assertion_and_preserves_strength(self):
        old = b'''        self.assertEqual(rendered.count('"shell": "bash"'), 3)\n'''
        adapted = export.public_toolkit_test(old).decode()
        self.assertIn("'), 9)", adapted)
        self.assertIn("PostToolUseFailure", adapted)
        with self.assertRaises(export.ExportError):
            export.public_toolkit_test(b"unreviewed new public test")

    def test_scanner_does_not_mistake_relative_home_feature_for_user_directory(self):
        self.assertEqual(export.review_content("example.md", b"`features/home/src/main/ets/`"), [])
        self.assertEqual(export.review_content("example.md", b'"/home/synthetic-person/project"')[0]["kind"],
                         "absolute-user-path")

    @unittest.skipIf(os.name == "nt", "POSIX launcher process; Windows execution is a separate gate")
    def test_real_launcher_preserves_stdin_and_exit_for_every_entry(self):
        root = self.root / "launcher-fixture"
        root.mkdir()
        launcher = root / "run-hook.sh"
        launcher.write_bytes((ROOT / export.OVERLAY_PREFIX / "hooks/run-hook.sh").read_bytes())
        kb = self.root / "synthetic-kb"
        interpreter = kb / "venv/bin/python"
        interpreter.parent.mkdir(parents=True)
        interpreter.symlink_to(sys.executable)
        environment = {**os.environ, "SULDE_KB_HOME": str(kb), "PYTHONDONTWRITEBYTECODE": "1"}
        for script in export.HOOK_SCRIPTS:
            (root / script).write_text("import sys\nsys.stdout.buffer.write(sys.stdin.buffer.read())\nsys.exit(17)\n")
            result = subprocess.run(["/bin/sh", str(launcher), script], input='{"synthetic":"中文"}',
                                    text=True, encoding="utf-8", errors="replace", capture_output=True, env=environment, timeout=10)
            self.assertEqual(result.returncode, 17, result.stderr)
            self.assertEqual(result.stdout, '{"synthetic":"中文"}')
        for selector in ("../outside.py", "unknown.py", "pre_tool_use.py; echo bypass"):
            result = subprocess.run(["/bin/sh", str(launcher), selector], capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", env=environment, timeout=10)
            self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
