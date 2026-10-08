import hashlib,json,os,pathlib,shutil,subprocess,sys,tempfile,time

root=pathlib.Path.cwd()
base=pathlib.Path(tempfile.mkdtemp(prefix="life-candidate-")).resolve()
env={k:v for k,v in os.environ.items() if k in {"PATH","TMPDIR","LANG","LC_ALL"}}
home=base/"home"
home.mkdir()
env.update(HOME=str(home),CODEX_HOME=str(home/".codex"),SULDE_HOME=str(home/".sulde"),
           SULDE_KB_HOME=str(home/".sulde/data/kb"),SULDE_LAUNCHAGENTS_DIR=str(home/"launchagents"),
           PYTHONDONTWRITEBYTECODE="1")
env["SULDE_CANDIDATE_PYTHON"]=sys.argv[1]
(home/".codex").mkdir()
codex=shutil.which("codex")
prefix=[sys.argv[1],"-B",str(root/"scripts/release/candidate_codex_plugin.py"),"--candidate-home",str(base/"candidates"),"--codex",codex,"--json"]
evidence={"schema":"life-candidate-probe-v1","source_commit":subprocess.run(["git","rev-parse","HEAD"],capture_output=True,text=True,encoding="utf-8",errors="replace",check=True).stdout.strip(),"codex_sha256":hashlib.sha256(pathlib.Path(codex).resolve().read_bytes()).hexdigest(),"candidate_root":str(base),"production_touched":False,"runs":[]}
for candidate,fault in (("normal",None),("failure","hook_invalid_json")):
    for phase,args in (("prepare",["prepare","--candidate-id",candidate]),("verify",["verify",candidate]+(["--fault",fault] if fault else []))):
        start=time.monotonic()
        completed=subprocess.run(prefix+args,cwd=root,env=env,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=180)
        item={"candidate":candidate,"phase":phase,"exit_code":completed.returncode,"seconds":round(time.monotonic()-start,3)}
        statepath=base/"candidates"/candidate/"state.json"
        if statepath.exists():
            state=json.loads(statepath.read_text(encoding="utf-8"))
            item.update(status=state.get("status"),timings_ms=state.get("timings_ms"),verification_keys=list(state.get("verification",{})),promotion_consumed=state.get("promotion_consumed"))
            item["state_sha256"]=hashlib.sha256(statepath.read_bytes()).hexdigest()
        if completed.returncode:
            # This isolated CLI error contains no business prompt or tool result.
            print("FAILURE_DETAIL",completed.stderr[-600:],completed.stdout[-600:],flush=True)
        evidence["runs"].append(item)
        print(json.dumps(item),flush=True)
        if phase=="prepare" and completed.returncode:
            break
pathlib.Path("/private/tmp/life-candidate-evidence.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")
print("ROOT",base,flush=True)
