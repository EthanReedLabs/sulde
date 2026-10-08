"""Diagnose policy path identity against disposable fixtures, not production.

Uses the unmodified isolation command builder and preflight. Every write target
is owned by this probe; records observations without claiming release readiness.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "diagnostic_isolation", ROOT / "scripts/kb/run-isolated-tests.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
OUTPUT = ROOT / ".sulde/native-failure-diagnosis/path-boundary"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=False, mode=0o700)
    rows = []
    source = (
        "import sys\nfrom pathlib import Path\n"
        "try:\n Path(sys.argv[1]).write_text('diagnostic-owned')\n"
        "except PermissionError:\n print('denied')\n"
        "else:\n print('written')\n"
    )
    for parent in (os.environ["TMPDIR"], "/tmp", "/private/tmp"):
        with tempfile.TemporaryDirectory(prefix="sulde-path-proof-", dir=parent) as name:
            fixture = Path(name)
            protected = fixture / "fixture-protected"
            protected.mkdir()
            env = module.isolated_environment(
                fixture / "isolated", production_kb=protected,
                inherited={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"})
            variants = (("positive-control", None), ("raw-policy", protected),
                        ("canonical-policy", protected.resolve()))
            for label, policy_root in variants:
                target = protected / label
                inner = [sys.executable, "-S", "-c", source, str(target)]
                command = (inner if policy_root is None else
                           module.os_isolated_test_command(inner, policy_root))
                result = subprocess.run(command, cwd=ROOT, env=env,
                                        text=True, capture_output=True, timeout=20)
                rows.append({"parent": parent, "variant": label,
                             "root": str(protected), "real_root": str(protected.resolve()),
                             "policy_root": str(policy_root) if policy_root else None,
                             "target": str(target), "command": command,
                             "exit_code": result.returncode,
                             "stdout": result.stdout, "stderr": result.stderr,
                             "target_exists": target.exists()})
            for label, policy_root in (("raw", protected), ("canonical", protected.resolve())):
                try:
                    module.preflight_os_test_isolation(policy_root, env)
                except RuntimeError as error:
                    outcome = {"status": "rejected", "error": str(error)}
                else:
                    outcome = {"status": "verified_write_denial"}
                rows.append({"parent": parent, "variant": "original-preflight-" + label,
                             "policy_root": str(policy_root), **outcome})
    payload = {"schema": "sulde-path-boundary-diagnosis-v1",
               "source_sha256": hashlib.sha256(
                   (ROOT / "scripts/kb/run-isolated-tests.py").read_bytes()).hexdigest(),
               "python": sys.executable, "rows": rows,
               "all_targets_disposable": True, "product_source_modified": False}
    path = OUTPUT / "evidence.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)
    for row in rows:
        print(json.dumps({key: row[key] for key in (
            "parent", "variant", "exit_code", "stdout", "target_exists", "status", "error"
        ) if key in row}))


if __name__ == "__main__":
    main()
