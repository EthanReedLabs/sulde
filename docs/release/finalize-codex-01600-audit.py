"""Read back bounded audit evidence; seal a self-excluding digest inventory."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path("/Volumes/Optimus/Sulde/tasks/codex-01600-compat-20261003")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    os.umask(0o077)
    results = {}
    for name in ["baseline-surfaces", "baseline-injection", "candidate-injection",
                 "candidate-entry", "candidate-native", "candidate-regression",
                 "candidate-regression-remainder"]:
        run = json.loads((EVIDENCE / name / "run.json").read_text())
        assert run["cli_identity_unchanged"]
        assert run["exit_code"] == (-15 if name == "candidate-regression" else 0), (name, run["exit_code"])
        log = EVIDENCE / name / "tests.log"
        summary = {"exit_code": run["exit_code"], "elapsed_seconds": run["elapsed_seconds"]}
        if log.exists():
            assert sha(log) == run["log_sha256"]
            summary["suite_summary"] = re.findall(r"^Ran .*|^OK.*|^FAILED.*", log.read_text(), re.MULTILINE)
        if name.startswith("candidate-"):
            checked = {p: h for p, h in run["source_sha256"].items() if p.startswith(("scripts/", "tests/"))}
            assert all((ROOT / p).is_file() and sha(ROOT / p) == h for p, h in checked.items()), name
            summary["current_source_test_hashes_match"] = len(checked)
        if name == "candidate-regression-remainder":
            before, ran, reused = map(set, [run["selected_before_reuse"], run["selected_to_run"], run["reuse"]["tests"]])
            assert not ran & reused and ran | reused == before
            assert run["reuse"]["log_sha256"] == sha(EVIDENCE / "candidate-regression/tests.log")
            assert all(row["covered_by"] in before for row in run["inherited_duplicates"])
            summary.update(unique_cases=len(before), newly_selected=len(ran), reused_passes=len(reused),
                           inherited_duplicates=len(run["inherited_duplicates"]))
        results[name] = summary
    surfaces = json.loads((EVIDENCE / "baseline-surfaces/run.json").read_text())
    assert all(sha(EVIDENCE / "baseline-surfaces" / p) == h for p, h in surfaces["schema_sha256"].items())
    native = json.loads((EVIDENCE / "candidate-os-boundary/summary.json").read_text())
    assert sha(EVIDENCE / "candidate-os-boundary/native-evidence.json") == native["evidence_sha256"]
    assert native["prevented"] == 17 and native["probe_count"] == 19
    assert sha(ROOT / "scripts/kb/native_agent_broker.py") == native["source_sha256"]
    executable = Path(shutil.which("codex")).resolve(strict=True)
    version = subprocess.run([str(executable), "--version"], capture_output=True, text=True, timeout=10)
    assert version.returncode == 0 and version.stdout.strip() == "codex-cli 0.160.0"
    assert sha(executable) == surfaces["cli_sha256"]
    # Resolve the installed NPM wrapper's dependency, rather than mislabel its
    # stable JavaScript digest as the compiled CLI binary's identity.
    resolver = 'const {createRequire}=require("module"); const p=require("path"); const r=createRequire(process.argv[1]); console.log(p.join(p.dirname(r.resolve("@openai/codex-darwin-arm64/package.json")),"vendor/aarch64-apple-darwin/bin/codex"));'
    payload = Path(subprocess.check_output(["node", "-e", resolver, str(executable)], text=True).strip()).resolve(strict=True)
    compiled = subprocess.run([str(payload), "--version"], capture_output=True, text=True, timeout=10)
    assert compiled.returncode == 0 and compiled.stdout == version.stdout
    source_dir = EVIDENCE / "final-source"
    source_dir.mkdir(exist_ok=False)
    changed = subprocess.check_output(["git", "diff", "--name-only", "dev"], cwd=ROOT, text=True).splitlines()
    changed += subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "docs/release"], cwd=ROOT, text=True).splitlines()
    for relative in sorted(set(changed)):
        source = ROOT / relative
        if source.is_file():
            destination = source_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    (EVIDENCE / "candidate.patch").write_bytes(subprocess.check_output(["git", "diff", "dev"], cwd=ROOT))
    summary = {"status": "scoped_candidate_checks_passed_not_independently_accepted",
               "model_calls": 0, "production_install": False, "runs": results,
               "schema_files": len(surfaces["schema_sha256"]), "native_permission_boundary": native,
               "host_version": version.stdout.strip(), "cli_launcher_sha256": sha(executable),
               "compiled_payload_sha256": sha(payload), "help_sha256": surfaces["help_observation_sha256"],
               "source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()}
    with (EVIDENCE / "SUMMARY.json").open("x") as stream:
        json.dump(summary, stream, indent=2)
        stream.write("\n")
    manifest = {}
    for path in sorted(EVIDENCE.rglob("*")):
        if path.is_file() and not path.is_symlink() and path.name != "FINAL-SHA256.json":
            path.chmod(0o600)
            manifest[str(path.relative_to(EVIDENCE))] = sha(path)
    with (EVIDENCE / "FINAL-SHA256.json").open("x") as stream:
        json.dump(manifest, stream, sort_keys=True, indent=2)
        stream.write("\n")
    assert all(sha(EVIDENCE / p) == h for p, h in manifest.items())
    print(json.dumps({"runs": results, "verified_files": len(manifest), "model_calls": 0}, indent=2))


if __name__ == "__main__":
    main()
