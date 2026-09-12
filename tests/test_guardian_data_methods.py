"""Data-method regressions; never execute any classified destructive command."""
from __future__ import annotations

import shlex
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "kb"))
from intent_guardian_parts.resources import _python_source_effect, normalize_hook_event
from intent_guardian_parts.policy import evaluate_event
from intent_guardian_parts.state import default_contract


class GuardianDataMethodTests(unittest.TestCase):
    def event(self, source: str) -> dict:
        return normalize_hook_event(
            {"tool_name": "exec_command", "tool_input": {
                "cmd": "python3 -c " + shlex.quote(source),
            }}, phase="started", provider="codex",
        )

    def test_literal_data_methods_are_read(self) -> None:
        for source in (
            "print('before'.replace('before', 'after'))",
            "text = 'before'; print(text.replace('before', 'after'))",
            "values = ['a', 'b']; values.remove('a'); print(values)",
            "print(b'abc'.replace(b'a', b'b'))",
            "print('before'.replace('b', 'a').replace('a', 'c'))",
        ):
            with self.subTest(source=source):
                self.assertEqual(_python_source_effect(source, cwd=None), "read")
                self.assertEqual(self.event(source)["effect"], "read")

    def test_script_write_with_data_replace_is_not_destructive(self) -> None:
        source = (
            "from pathlib import Path; text = 'before'; "
            "Path('probe.py').write_text(text.replace('before', 'after'))"
        )
        self.assertEqual(_python_source_effect(source, cwd=None), "local_write")
        self.assertEqual(self.event(source)["effect"], "local_write")

    def test_real_filesystem_methods_remain_destructive(self) -> None:
        for source in (
            "import os; os.replace('a', 'b')",
            "from os import remove as erase; erase('a')",
            "from pathlib import Path; Path('a').replace('b')",
            "from pathlib import Path as P; target=P('a'); target.unlink()",
            "import shutil; shutil.rmtree('a')",
        ):
            with self.subTest(source=source):
                self.assertEqual(self.event(source)["effect"], "destructive")

    def test_uncertain_receivers_cannot_borrow_a_literal_type(self) -> None:
        for source in (
            "value='a'; value=target; value.replace('a', 'b')",
            "value='a'; exec(code); value.replace('a', 'b')",
            "value='a'\ndef f(value):\n value.replace('a', 'b')",
            "value='a'\nif flag:\n value=target\nvalue.replace('a', 'b')",
            "value=['a']; globals()['value']=target; value.remove('a')",
            "value=[target]; value.remove(other)",
            "value.remove('a'); value=['a']",
            "value=['a']; value.append(target); value.remove('a')",
            "value=['a']; alias=value; alias.append(target); value.remove('a')",
            "value=['a']; mutate(value); value.remove('a')",
        ):
            with self.subTest(source=source):
                self.assertNotEqual(self.event(source)["effect"], "read")

    def test_destructive_execution_inside_data_arguments_is_not_hidden(self) -> None:
        source = "import os; print('abc'.replace(str(os.remove('a')), 'b'))"
        self.assertEqual(self.event(source)["effect"], "destructive")

    def test_mutation_and_nested_scopes_invalidate_borrowed_type(self) -> None:
        for source in (
            "value='a'; mutate(); value.replace('a','b')",
            "value='a'; namespace.value=other; value.replace('a','b')",
            "value='a'; namespace['value']=other; value.replace('a','b')",
            "value='a'\ndef later():\n return value.replace('a','b')",
            "value='a'; later=lambda: value.replace('a','b')",
            "import builtins; builtins.print=mutate; value='a'; print(); value.replace('a','b')",
        ):
            with self.subTest(source=source):
                self.assertEqual(self.event(source)["invocation_violation"]["kind"],
                                 "unresolved-destructive-receiver")

    def test_transport_and_extra_arguments_cannot_hide_destructive_calls(self) -> None:
        for command, effect in (
            ("python3 -c \"print('$PAYLOAD'.replace('a','b'))\"", "unknown"),
            (shlex.join(["python3", "-c", "import os; os.remove('a')", "argument"]), "destructive"),
            ("node -e 'console.log(1)'\npython3 -c 'import os; os.remove(\"a\")'", "destructive"),
        ):
            event = normalize_hook_event({"tool_name": "exec_command", "tool_input": {
                "cmd": command}}, phase="started", provider="codex")
            self.assertEqual(event["effect"], effect, command)
            if effect == "unknown":
                self.assertEqual(event["invocation_violation"]["kind"], "unresolved-destructive-receiver")

    def test_unknown_receiver_is_hard_denied_without_pre_execution_pause(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract = default_contract(
                intent_id="data-methods", objective="classify data safely",
                acceptance_criteria=["no false pause"], workspace=Path(directory),
                mode="enforce", confirmed_by="test",
            )
            event = self.event("receiver.remove('target')")
            self.assertEqual(event["effect"], "unknown")
            self.assertEqual(event["uncertainty_kind"], "unresolved_destructive_receiver")
            for mode in ("enforce", "shadow"):
                contract["mode"] = mode
                decision = evaluate_event(contract, event)
                self.assertEqual(decision.action, "deny")
                self.assertFalse(decision.pause)
            contract["mode"] = "enforce"
            event["phase"] = "completed"
            decision = evaluate_event(contract, event)
            self.assertTrue(decision.pause)
            self.assertTrue(decision.verification_required)

    def test_known_write_cannot_launder_unknown_destructive_receiver(self) -> None:
        event = self.event("from pathlib import Path; Path('ok').write_text('ok'); receiver.remove('other')")
        self.assertEqual(event["effect"], "unknown")
        self.assertEqual(event["invocation_violation"]["kind"], "unresolved-destructive-receiver")

    def test_bytecode_free_python_flags_keep_the_typed_effect(self) -> None:
        for source, effect in (("print('a'.replace('a', 'b'))", "read"),
                               ("from pathlib import Path\nPath('probe').write_text('a'.replace('a','b'))", "local_write"),
                               ("receiver.remove('unproved')", "unknown"),
                               ("import os; os.remove('no')", "destructive")):
            event = normalize_hook_event({"tool_name": "exec_command", "tool_input": {
                "cmd": shlex.join([sys.executable, "-B", "-c", source])}}, phase="started", provider="codex")
            self.assertEqual(event["effect"], effect, source)


if __name__ == "__main__":
    unittest.main()
