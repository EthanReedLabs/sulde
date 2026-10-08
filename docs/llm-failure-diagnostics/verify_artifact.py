"""Local fixed-purpose staging verification, not install or model execution.

Uses the preserved pilot verifier; no portable CI or full-release claim.
All product subprocesses have network denied and task-only writes.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

report_dir = Path(__file__).resolve().parent
task = report_dir.parents[1]
dev = task.parent / "guardian-v3-dev-merge"
pilot = task.parent / "orca-sulde-diagnostics-pilot"
scratch = pilot / ".pilot-runtime"
python = "/Users/eric/.sulde/data/kb/venv/bin/python"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=dev, text=True).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digest(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or "__pycache__" in path.parts or path.suffix == ".pyc":
            raise RuntimeError("unexpected alias or bytecode in artifact")
        if path.is_file():
            relative = path.relative_to(root).as_posix().encode()
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            digest.update(path.read_bytes())
    return digest.hexdigest()


assert git("branch", "--show-current") == "dev"
assert not git("status", "--porcelain")
head = git("rev-parse", "HEAD")
previous = json.loads((report_dir / "fix-checks-v8ecbs2w.json").read_text())
# Reuse evidence only when every scoped implementation/test digest still matches.
for relative, digest in previous["source_and_test_sha256"].items():
    assert sha(dev / relative) == digest, relative
run = Path(tempfile.mkdtemp(prefix="artifact-checks-", dir=scratch))
private_home = run / "home"
private_home.mkdir(mode=0o700)
profile = report_dir / "artifact-offline.sb"
sandbox = ["/usr/bin/sandbox-exec"]
for key, value in {"TASK": dev, "PILOT": pilot, "RUNTIME": scratch,
                   "GITDIR": Path(git("rev-parse", "--git-common-dir")).resolve(),
                   "USERROOT": "/Users/eric", "VENV": "/Users/eric/.sulde/data/kb/venv",
                   "PYTHONROOT": "/Users/eric/.pyenv/versions/3.10.7"}.items():
    sandbox += ["-D", f"{key}={value}"]
sandbox += ["-f", str(profile)]
env = {"PATH": "/usr/bin:/bin", "HOME": str(private_home), "TMPDIR": str(run),
       "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_NOSYSTEM": "1", "LC_CTYPE": "UTF-8"}
report = {"schema": "llm-diagnostic-artifact-check-v1", "source_commit": head,
          "source_clean": True, "network": "denied", "model_calls": 0,
          "installed": False, "scoped_evidence_reused": "fix-checks-v8ecbs2w.json",
          "runner_sha256": sha(Path(__file__)), "profile_sha256": sha(profile), "steps": []}


def execute(label, argv, timeout=120):
    result = subprocess.run(sandbox + argv, cwd=dev, env=env, capture_output=True,
                            text=True, timeout=timeout)
    report["steps"].append({"label": label, "exit_code": result.returncode,
                            "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
                            "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest()})
    if result.returncode:
        print(result.stderr[-3000:].replace(str(dev), "<dev>").replace(str(pilot), "<pilot>"))
        raise RuntimeError(label + " failed")
    return result


try:
    output = run / "codex"
    execute("stage_codex_posix", [python, "-B", str(dev / "scripts/release/stage_plugin.py"),
                                  "--target", "codex", "--platform", "posix", "--output", str(output)])
    plugin = output / "plugins/sulde"
    runtime = plugin / "runtime"
    generation = json.loads((plugin / ".codex-plugin/generation.json").read_text())
    report["artifact_generation"] = generation
    before = tree_digest(runtime)
    assert before == generation["runtime_tree_sha256"]
    report["files"] = {}
    for name in ("auto-distill.py", "self-repair.py", "llm_diagnostics.py"):
        relative = "scripts/kb/" + name
        assert sha(runtime / relative) == sha(dev / relative)
        report["files"][relative] = sha(runtime / relative)
    for interpreter in (python, "/usr/bin/python3"):
        for name in ("auto-distill.py", "self-repair.py"):
            result = execute(Path(interpreter).name + ":" + name + ":help",
                             [interpreter, "-B", str(runtime / "scripts/kb" / name), "--help"])
            assert "usage:" in result.stdout.lower()
    evidence = run / "independent.json"
    execute("artifact_independent", [python, "-B", str(pilot / "docs/orca-sulde-diagnostics-pilot/verify_diagnostics.py"),
                                      "--source", str(runtime), "--scratch-root", str(scratch),
                                      "--report", str(evidence)], timeout=30)
    report["independent"] = json.loads(evidence.read_text())
    assert len(report["independent"]["checks"]) == 44
    assert all(row["pass"] for row in report["independent"]["checks"])
    assert tree_digest(runtime) == before
    assert git("rev-parse", "HEAD") == head and not git("status", "--porcelain")
    report["artifact_unchanged"] = True
    report["status"] = "passed"
except Exception as error:
    report["status"] = "failed"
    report["error_type"] = type(error).__name__
    raise
finally:
    destination = report_dir / (run.name + ".json")
    with destination.open("x") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    os.chmod(destination, 0o600)
    print(json.dumps({"report": destination.name, "status": report.get("status", "failed")}))
