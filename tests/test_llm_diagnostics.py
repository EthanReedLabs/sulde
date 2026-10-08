"""Offline regression: safe failure summaries, not arbitrary output redaction."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import traceback
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/kb"))
import llm_diagnostics as diagnostic


def load(filename, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts/kb" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class DiagnosticTests(unittest.TestCase):
    def message(self, text, *, prompt="synthetic prompt", stdout=""):
        return diagnostic.process_failure(text, stdout, 1, prompt)

    def test_tail_survives_long_banner(self):
        result = self.message("banner\n" * 10000 + "ERROR insufficient_quota: private account detail\n")
        self.assertTrue(result.startswith("[quota]"))
        self.assertIn("scan=truncated", result)
        self.assertNotIn("private account", result)

    def test_unknown_not_inferred_from_exit(self):
        self.assertTrue(self.message("banner\n" * 2000).startswith("[unknown]"))
        self.assertTrue(self.message("Error: HTTP 429").startswith("[unknown]"))

    def test_stdout_fallback_and_stderr_precedence(self):
        self.assertTrue(self.message(" \n", stdout="ERROR request_timeout").startswith("[timeout]"))
        self.assertTrue(self.message("unclassified stderr", stdout="ERROR request_timeout").startswith("[unknown]"))

    def test_provider_structured_codes_only(self):
        for value, expected in (({"error": {"code": "insufficient_quota"}}, "quota"),
                                ({"error": {"message": "insufficient_quota"}}, "unknown"),
                                ({"error": {"code": "insufficient_quota", "type": "timeout"}}, "unknown"),
                                ({"error": {"code": "timeout"}, "prompt": "echo"}, "unknown"),
                                ({"error": {"code": ["timeout"]}}, "unknown")):
            self.assertTrue(self.message(json.dumps(value)).startswith(f"[{expected}]"))

    def test_explicit_text_timeout_and_usage_limit(self):
        for text, expected in (("Error: Operation timed out", "timeout"),
                               ("ERROR: You've hit your usage limit.", "quota"),
                               ("Error: insufficient quota", "quota")):
            self.assertTrue(self.message(text).startswith(f"[{expected}]"))

    def test_conflict_is_unknown(self):
        self.assertTrue(self.message("ERROR insufficient_quota\nERROR request_timeout").startswith("[unknown]"))

    def test_echo_fence_quoted_block_and_embedded_word_not_evidence(self):
        for text in ('Quoted user prompt: "ERROR insufficient_quota"',
                     "Quoted user prompt:\nERROR insufficient_quota\n",
                     "```\nERROR insufficient_quota\n```",
                     'Error: "insufficient_quota" is in the prompt',
                     "request contains quota or timeout", "> ERROR insufficient_quota"):
            self.assertTrue(self.message(text).startswith("[unknown]"))

    def test_known_prompt_echo_at_torn_window_is_not_evidence(self):
        prompt = "synthetic context\n" * 1000 + "ERROR insufficient_quota\n"
        self.assertTrue(self.message(prompt, prompt=prompt).startswith("[unknown]"))

    def test_fence_across_truncated_region_is_unknown(self):
        self.assertTrue(self.message("```\n" + "banner\n" * 10000 + "ERROR insufficient_quota").startswith("[unknown]"))

    def test_boundary_capacity_and_controls(self):
        for size in (0, 1, 4095, 4096, 8191, 8192, 8193, 100000):
            result = self.message("中" * size + "\n\x1b[31mERROR insufficient_quota\x1b[0m\n")
            self.assertLessEqual(len(result.encode()), diagnostic.MAX_SUMMARY_BYTES)
            self.assertNotIn("\x1b", result)
            self.assertNotIn("中", result)
            self.assertNotIn("\ufffd", result)
            self.assertIn("raw_output=omitted", result)

    def test_no_secret_or_private_path_in_any_returned_summary(self):
        secret = "synthetic-private-token-19ab"
        text = (f"Authorization: Bearer {secret}\nhttps://user:{secret}@example.invalid\n"
                f"/Users/synthetic-private/secret\n{secret}\nERROR insufficient_quota")
        result = self.message(text)
        self.assertNotIn(secret, result)
        self.assertNotIn("/Users/", result)
        self.assertNotIn("example.invalid", result)


class EntryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.distill = load("auto-distill.py", "failure_test_distill")
        cls.repair = load("self-repair.py", "failure_test_repair")

    def entries(self):
        return ((self.distill, self.distill.run_llm, self.distill.DistillError),
                (self.repair, self.repair.run_command_template, self.repair.SelfRepairError))

    def test_timeout_and_startup_do_not_retain_raw_exception_chain(self):
        secret = "synthetic-secret-in-command-and-output"
        for module, invoke, error_type in self.entries():
            for error, category in ((subprocess.TimeoutExpired([secret], 1, output=secret, stderr=secret), "timeout"),
                                    (FileNotFoundError(2, secret, "/Users/private/" + secret), "startup_failure")):
                with patch.object(module.subprocess, "run", side_effect=error):
                    try:
                        invoke("fake {prompt}", secret)
                    except error_type as actual:
                        self.assertTrue(str(actual).startswith(f"[{category}]"))
                        self.assertIsNone(actual.__context__)
                        self.assertIsNone(actual.__cause__)
                        rendered = "".join(traceback.format_exception(type(actual), actual, actual.__traceback__))
                        self.assertNotIn(secret, rendered)
                    else:
                        self.fail("Expected controlled failure")

    def test_template_setup_failure_drops_original_exception_context(self):
        secret = "synthetic-secret-template"
        for module, invoke, error_type in self.entries():
            with self.subTest(entry=module.__name__):
                with patch.object(module, "split_command_template", side_effect=ValueError(secret)):
                    try:
                        invoke("fake", secret)
                    except error_type as actual:
                        self.assertTrue(str(actual).startswith("[startup_failure]"))
                        self.assertIsNone(actual.__context__)
                        self.assertIsNone(actual.__cause__)
                        self.assertNotIn(secret, str(actual))
                    else:
                        self.fail("Expected controlled failure")
            for template in ("", 'fake "unterminated'):
                with self.subTest(entry=module.__name__, template=template):
                    with patch.object(module.subprocess, "run") as run:
                        with self.assertRaises(error_type) as raised:
                            invoke(template, secret)
                        self.assertTrue(str(raised.exception).startswith("[startup_failure]"))
                        self.assertIsNone(raised.exception.__context__)
                        self.assertIsNone(raised.exception.__cause__)
                        run.assert_not_called()

    def test_success_preserves_exact_output_even_when_it_contains_error_words(self):
        for module, invoke, _ in self.entries():
            result = subprocess.CompletedProcess([], 0, "ERROR insufficient_quota\n中文🧪\n", "warning")
            with patch.object(module.subprocess, "run", return_value=result) as call:
                self.assertEqual(invoke("fake {prompt}", "中文prompt"), result.stdout)
                self.assertEqual(call.call_count, 1)
                self.assertEqual(call.call_args.kwargs["input"], "中文prompt")

    def test_failed_process_summary_cannot_leak_prompt(self):
        for module, invoke, error_type in self.entries():
            result = subprocess.CompletedProcess([], 1, "", "synthetic-secret\n" * 1000 + "ERROR insufficient_quota")
            with patch.object(module.subprocess, "run", return_value=result):
                with self.assertRaises(error_type) as raised:
                    invoke("fake {prompt}", "synthetic-secret")
                self.assertTrue(str(raised.exception).startswith("[quota]"))
                self.assertNotIn("synthetic-secret", str(raised.exception))

    def test_invalid_schema_classification_and_no_decode_context(self):
        for raw in ("secret-not-json", "[]", '{"entities":[],"edges":[],"lessons":[{}]}'):
            with self.assertRaises(self.distill.DistillError) as raised:
                self.distill.parse_result(raw)
            self.assertTrue(str(raised.exception).startswith("[invalid_output]"))
            self.assertIsNone(raised.exception.__context__)
            self.assertNotIn("secret-not-json", str(raised.exception))

    def test_minimal_module_load_and_brief_failure(self):
        with self.assertRaises(self.repair.SelfRepairError) as raised:
            self.repair.clean_brief("synthetic-invalid-brief")
        self.assertTrue(str(raised.exception).startswith("[invalid_output]"))


if __name__ == "__main__":
    unittest.main()
