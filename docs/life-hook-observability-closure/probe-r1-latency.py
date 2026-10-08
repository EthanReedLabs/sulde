"""Same-interpreter paired wrapper measurements. Budgets fixed in R1.md first."""
import ast
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = Path("integrations/codex/plugins/sulde/scripts")


def summary(values):
    return {"n": len(values), "median_ms": round(statistics.median(values), 3),
            "p95_ms": round(sorted(values)[math.ceil(len(values) * .95) - 1], 3), "samples_ms": values}


def main():
    base = Path(tempfile.mkdtemp(prefix="life-r1-perf-")).resolve()
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "TMPDIR", "LANG", "LC_ALL"}}
    bin_dir = base / "bin"
    bin_dir.mkdir()
    (bin_dir / "python3").symlink_to(sys.executable)
    env.update(PATH=str(bin_dir) + os.pathsep + env.get("PATH", ""), PYTHONDONTWRITEBYTECODE="1")
    commands = {}
    identities = {}
    for label, revision in (("no_observer", "f687193"), ("before", "c33d7b9"), ("after", None)):
        scripts = base / label / "plugin/scripts"
        scripts.mkdir(parents=True)
        for filename in ("run-hook.sh", "_hook_observer.py", "_hook_entry.py"):
            source = SCRIPTS / filename
            if revision:
                result = subprocess.run(["git", "show", revision + ":" + str(source)], cwd=ROOT, capture_output=True)
                if result.returncode:
                    continue
                content = result.stdout
            elif (ROOT / source).exists():
                content = (ROOT / source).read_bytes()
            else:
                continue
            (scripts / filename).write_bytes(content)
            identities[label + "/" + filename] = hashlib.sha256(content).hexdigest()
        (scripts / "post-tool-use.py").write_text("import os\nraise SystemExit(int(os.environ.get('FIXTURE_EXIT', '0')))\n")
        home = base / label / "home"
        home.mkdir()
        local = {**env, "HOME": str(home), "SULDE_HOME": str(home / ".sulde"), "SULDE_KB_HOME": str(home / ".sulde/data/kb")}
        commands[label] = (["sh", str(scripts / "run-hook.sh"), "post-tool-use"], local)
        bridge_home = base / label / "bridge-home"
        bridge = bridge_home / ".sulde/bin/intent-guardian"
        bridge.parent.mkdir(parents=True)
        relative = "scripts/kb/intent-guardian.py"
        source = (subprocess.check_output(["git", "show", revision + ":" + relative], cwd=ROOT).decode()
                  if revision else (ROOT / relative).read_text())
        function = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
                        and node.name == "_run_codex_adapter_in_process")
        body = "\n".join(source.splitlines()[function.lineno - 1:function.end_lineno])
        identities[label + "/bridge_adapter_function"] = hashlib.sha256(body.encode()).hexdigest()
        prelude = "#!/usr/bin/env python3\n"
        if revision is None:
            prelude += "# sulde-observer-in-process-v1\n"
        prelude += "import io,os,runpy,subprocess,sys,traceback\nfrom pathlib import Path\n"
        bridge.write_text(prelude + body + "\nresult=_run_codex_adapter_in_process(Path(" + repr(str(scripts / "post-tool-use.py"))
                          + "), environment=dict(os.environ), input_bytes=sys.stdin.buffer.read())\n"
                          "sys.stdout.buffer.write(result.stdout)\nsys.stderr.buffer.write(result.stderr)\nraise SystemExit(result.returncode)\n")
        bridge.chmod(0o700)
        commands[label + "/bridge"] = (commands[label][0], {**local, "HOME": str(bridge_home),
            "SULDE_HOME": str(bridge_home / ".sulde"), "SULDE_KB_HOME": str(bridge_home / ".sulde/data/kb")})
    samples = {}
    for failure, count in ((False, 60), (True, 30)):
        phase = "failure" if failure else "normal"
        for i in range(count + 5):
            for label, (argv, local) in commands.items():
                started = time.perf_counter()
                result = subprocess.run(argv, input=json.dumps({"session_id": "fixture", "cwd": str(base), "tool_use_id": f"{phase}-{i}"}),
                                        env={**local, "FIXTURE_EXIT": "1" if failure else "0"}, capture_output=True, text=True, timeout=5)
                elapsed = round((time.perf_counter() - started) * 1000, 3)
                assert result.returncode == 0, result.stderr
                if i >= 5:
                    samples.setdefault(label + "/" + phase, []).append(elapsed)
    # Differential fresh-process controls, not a fabricated additive cost model.
    snippets = {"process": "pass", "imports": "import argparse,sqlite3,subprocess,threading,uuid,signal,json,hashlib,datetime,pathlib"}
    for label, code in snippets.items():
        values = []
        for i in range(65):
            started = time.perf_counter()
            subprocess.run([sys.executable, "-B", "-c", code], env=env, capture_output=True, check=True)
            if i >= 5:
                values.append(round((time.perf_counter() - started) * 1000, 3))
        samples[label] = values
    observer = ROOT / SCRIPTS / "_hook_observer.py"
    spec = importlib.util.spec_from_file_location("perf_observer", observer)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for duplicate in (False, True):
        values = []
        for i in range(65):
            row = module.facts(hook="fixture", stage="adapter", payload={"tool_use_id": str(i)}, code=0, kind="normal")
            started = time.perf_counter()
            assert module.record(row, base / "sqlite")
            if i >= 5:
                values.append(round((time.perf_counter() - started) * 1000, 3))
        samples["sqlite_duplicate" if duplicate else "sqlite_insert"] = values
    result = {"schema": "life-r1-latency-v1", "platform": sys.platform, "python": sys.version,
              "python_sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(), "source": identities,
              "conditions": "5 warmups; paired round-robin fresh wrapper processes; same interpreter; temp HOME/data; no-effect adapter; bridge uses exact source function without Guardian pre-dispatch (not full production latency)",
              "samples": {key: summary(value) for key, value in samples.items()}}
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else base / "latency.json"
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"artifact": str(target), "summaries": {k: {x: y for x, y in v.items() if x != "samples_ms"} for k, v in result["samples"].items()}}))


if __name__ == "__main__":
    main()
