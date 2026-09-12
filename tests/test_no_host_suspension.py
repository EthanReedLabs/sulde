from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOTS = tuple(
    ROOT / name
    for name in ("scripts", "integrations", "hooks", "tools", "templates")
)
TASK_DEFINITIONS = ROOT / "guardian-program" / "task-definitions"
HISTORICAL_COMPOSITION = ROOT / "guardian-program" / "composition"
TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".yaml",
    ".yml",
}
SUSPENSION_PATTERN = re.compile(
    r"SIGSTOP|SIGTSTP|kill\s+-STOP|killpg\s*\([^\n]*SIG(?:STOP|TSTP)",
    re.IGNORECASE,
)
HISTORICAL_HELPERS = (
    "suspend_all_hosts_and_install",
    "coordinated_safe_point_install",
    "fleet_safe_point_install",
    "quiesce_resumed_session_and_install",
    "suspend_host_and_install",
    "fleet_bootstrap_install",
)


def _text_files(root: Path):
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            yield path


class NoHostSuspensionTests(unittest.TestCase):
    def test_production_and_task_definitions_never_suspend_codex_hosts(self) -> None:
        offenders: list[str] = []
        for root in (*PRODUCTION_ROOTS, TASK_DEFINITIONS):
            for path in _text_files(root):
                source = path.read_text(encoding="utf-8", errors="replace")
                if SUSPENSION_PATTERN.search(source):
                    offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])

    def test_production_and_task_definitions_do_not_reference_historical_helpers(self) -> None:
        offenders: list[str] = []
        for root in (*PRODUCTION_ROOTS, TASK_DEFINITIONS):
            for path in _text_files(root):
                source = path.read_text(encoding="utf-8", errors="replace")
                if any(helper in source for helper in HISTORICAL_HELPERS):
                    offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])

    def test_historical_composition_is_outside_production_source_roots(self) -> None:
        self.assertTrue(
            all(HISTORICAL_COMPOSITION not in root.parents and root != HISTORICAL_COMPOSITION
                for root in PRODUCTION_ROOTS)
        )
        matches = [
            path.relative_to(ROOT).as_posix()
            for path in _text_files(HISTORICAL_COMPOSITION)
            if SUSPENSION_PATTERN.search(
                path.read_text(encoding="utf-8", errors="replace")
            )
        ]
        self.assertTrue(
            all(path.startswith("guardian-program/composition/") for path in matches)
        )


if __name__ == "__main__":
    unittest.main()
