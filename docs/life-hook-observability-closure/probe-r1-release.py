"""Candidate verification and full isolated installation timings, not production.

Real source staging, Codex registry, hooks, MCP, launchers and installer run.
Only OS scheduler/process-list boundaries use explicit fixture executables.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import runpy
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    base = Path(tempfile.mkdtemp(prefix="life-r1-release-")).resolve()
    native = shutil.which("codex")
    assert native
    fixture = runpy.run_path(str(ROOT / "tests/test_codex_plugin_install.py"))
    evidence = {"schema": "life-r1-release-v1", "source_commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "platform": sys.platform,
        "python": sys.version, "python_sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
        "native_codex_sha256": hashlib.sha256(Path(native).resolve().read_bytes()).hexdigest(),
        "scope": "complete isolated installer; real Codex registry/hooks/MCP/launcher; fixture OS scheduler and process inventory",
        "production_changed": False, "runs": []}
    for number in range(3):
        root = base / str(number)
        home, bins = root / "home", root / "bin"
        home.mkdir(parents=True)
        bins.mkdir()
        (bins / "python3").symlink_to(sys.executable)
        for name, key in (("launchctl", "FAKE_LAUNCHCTL"), ("ps", "FAKE_PS")):
            path = bins / name
            path.write_text(fixture[key])
            path.chmod(0o700)
        env = {k: v for k, v in os.environ.items() if k in {"PATH", "TMPDIR", "LANG", "LC_ALL"}}
        env.update(HOME=str(home), CODEX_HOME=str(home / ".codex"), SULDE_HOME=str(home / ".sulde"),
                   SULDE_KB_HOME=str(home / ".sulde/data/kb"), SULDE_LAUNCHAGENTS_DIR=str(home / "launchagents"),
                   SULDE_CANDIDATE_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE="1", SULDE_TEST_MODE="1",
                   SULDE_LAUNCHCTL=str(bins / "launchctl"), SULDE_PS=str(bins / "ps"),
                   FAKE_LAUNCHCTL_STATE=str(root / "scheduler.json"), PATH=str(bins) + os.pathsep + env.get("PATH", ""))
        (home / ".codex").mkdir()
        prefix = [sys.executable, "-B", str(ROOT / "scripts/release/candidate_codex_plugin.py"),
                  "--candidate-home", str(root / "candidates"), "--codex", native, "--json"]
        for phase, argv in (("prepare", prefix + ["prepare", "--candidate-id", "candidate"]),
                            ("verify", prefix + ["verify", "candidate"]),
                            ("full_install", [sys.executable, "-B", str(ROOT / "scripts/release/install_codex_plugin.py"),
                             "--artifact-root", str(root / "installation-artifact"), "--kb-home", env["SULDE_KB_HOME"],
                             "--codex", native, "--json"])):
            started = time.perf_counter()
            if phase == "full_install":
                # Explicit environment preparation is included in full-install
                # timing. It copies the selected Python and shares its already
                # verified dependencies; no package download/global install.
                subprocess.run([sys.executable, "-B", "-m", "venv", "--copies", "--system-site-packages",
                                str(Path(env["SULDE_KB_HOME"]) / "venv")], env=env, check=True, capture_output=True)
            result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
            row = {"sample": number, "phase": phase, "seconds": round(time.perf_counter() - started, 3),
                   "exit_code": result.returncode}
            try:
                payload = json.loads(result.stdout)
                row["status"] = payload.get("status")
                if phase == "full_install":
                    row["phase_timings_seconds"] = payload.get("install_timings_seconds")
                if phase == "verify":
                    row["python_environment"] = payload.get("python", {}).get("environment")
                    row["verification"] = payload.get("verifications")
            except ValueError:
                pass
            evidence["runs"].append(row)
            print(json.dumps({key: value for key, value in row.items() if key not in {"verification", "python_environment"}}), flush=True)
            if result.returncode:
                print("ISOLATED_FAILURE=" + result.stderr[-1200:] + result.stdout[-1200:], flush=True)
                break
    evidence["summaries"] = {}
    for phase in ("prepare", "verify", "full_install"):
        values = [r["seconds"] for r in evidence["runs"] if r["phase"] == phase and r["exit_code"] == 0]
        if values:
            evidence["summaries"][phase] = {"n": len(values), "median_seconds": statistics.median(values),
                                             "p95_seconds": sorted(values)[math.ceil(len(values) * .95) - 1]}
    path = base / "release-evidence.json"
    path.write_text(json.dumps(evidence, indent=2) + "\n")
    print("RELEASE_EVIDENCE=" + str(path), flush=True)
    return 0 if len(evidence["runs"]) == 9 and all(r["exit_code"] == 0 for r in evidence["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
