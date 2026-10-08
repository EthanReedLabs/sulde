import hashlib, io, json, os, pathlib, shutil, statistics, subprocess, sys, tarfile, tempfile, time

root = pathlib.Path.cwd()
base = pathlib.Path(tempfile.mkdtemp(prefix="life-perf-")).resolve()
baseline = base / "baseline"
baseline.mkdir()
archive = subprocess.run(["git","archive","f687193bdda541d4651846ed99aa6dbe37475f7d"],capture_output=True,check=True).stdout
with tarfile.open(fileobj=io.BytesIO(archive),mode="r:") as bundle:
    bundle.extractall(baseline,filter="data")
env = {k:v for k,v in os.environ.items() if k in {"PATH","TMPDIR","LANG","LC_ALL"}}
env["PYTHONDONTWRITEBYTECODE"]="1"
for argv in (["git","init"],["git","add","."],["git","-c","user.name=Isolated","-c","user.email=isolated@example.invalid","commit","-m","baseline source fixture"]):
    subprocess.run(argv,cwd=baseline,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
results = {"schema":"life-latency-v1","baseline":"f687193bdda541d4651846ed99aa6dbe37475f7d","platform":sys.platform,
           "method":"10 fresh wrapper processes with no-effect adapter; one real staging and isolated Codex registry install per source; shared machine load, not a release SLA", "samples":{}}
for label, source in (("before",baseline),("after",root)):
    selected = base / label
    home = selected / "home"
    home.mkdir(parents=True)
    localenv = {**env,"HOME":str(home),"CODEX_HOME":str(home/".codex"),"SULDE_HOME":str(home/".sulde"),"SULDE_KB_HOME":str(home/".sulde/data/kb")}
    (home / ".codex").mkdir()
    wrapper = selected / "fixture/scripts"
    wrapper.mkdir(parents=True)
    for name in ("run-hook.sh","_hook_observer.py"):
        original = source / "integrations/codex/plugins/sulde/scripts" / name
        if original.exists():
            shutil.copy2(original,wrapper / name)
    (wrapper / "post-tool-use.py").write_text("print('{}')\n",encoding="utf-8")
    times=[]
    for i in range(10):
        started=time.perf_counter()
        result=subprocess.run(["sh",str(wrapper/"run-hook.sh"),"post-tool-use"],input=json.dumps({"session_id":"fixture","cwd":str(selected),"call_id":str(i)}),env=localenv,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=5)
        assert result.returncode == 0
        times.append(round((time.perf_counter()-started)*1000,3))
    phases=[]
    artifact = selected / "artifact"
    for phase,argv in (("stage",[sys.executable,"-B",str(source/"scripts/release/stage_plugin.py"),"--target","codex","--platform","posix","--output",str(artifact)]),
                       ("marketplace_add",["codex","plugin","marketplace","add",str(artifact),"--json"]),
                       ("plugin_add",["codex","plugin","add","sulde@sulde-local","--json"])):
        started=time.perf_counter()
        result=subprocess.run(argv,cwd=source,env=localenv,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=90)
        phases.append({"phase":phase,"ms":round((time.perf_counter()-started)*1000,3),"exit_code":result.returncode})
        if result.returncode:
            print(label,phase,"FAILED",result.stderr[-500:],flush=True)
            break
    results["samples"][label]={"ordinary_call_ms":times,"median_ms":statistics.median(times),"max_ms":max(times),"isolated_install_phases":phases,
                               "installer_scope":"staging_and_actual_Codex_registry_only; runtime_launchers_and_scheduler_not_in_this_timing"}
    print(label,json.dumps(results["samples"][label]),flush=True)
pathlib.Path("/private/tmp/life-perf-evidence.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
print("ARTIFACT_ROOT",base,flush=True)
