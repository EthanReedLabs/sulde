import hashlib, json, os, pathlib, selectors, shutil, subprocess, sys, tempfile, time

base = pathlib.Path(tempfile.mkdtemp(prefix="life-host-"))
home = base / "home"
home.mkdir()
workspace = base / "workspace"
workspace.mkdir()
env = {k:v for k,v in os.environ.items() if k in {"PATH","TMPDIR","LANG","LC_ALL"}}
env.update({"HOME": str(home), "CODEX_HOME": str(home / ".codex"), "SULDE_HOME": str(home / ".sulde"), "SULDE_KB_HOME": str(home / ".sulde/data/kb")})
pathlib.Path(env["CODEX_HOME"]).mkdir()
config = pathlib.Path(env["CODEX_HOME"]) / "config.toml"
configuration = 'check_for_update_on_startup = false\nmodel_provider = "isolated"\nmodel = "fixture"\n[features]\nhooks = true\n[model_providers.isolated]\nname = "Isolated unavailable endpoint"\nbase_url = "http://127.0.0.1:9/v1"\nwire_api = "responses"\nrequest_max_retries = 0\nstream_max_retries = 0\n'
configuration += '[projects.' + json.dumps(str(workspace.resolve())) + ']\ntrust_level = "trusted"\n'
config.write_text(configuration, encoding="utf-8")
(workspace / ".codex").mkdir()
(workspace / ".codex/hooks.json").write_text(json.dumps({"hooks":{"SessionStart":[{"matcher":"startup|resume|clear", "hooks":[{"type":"command","command":"sh -c 'exit 1'", "timeout":2}]}]}}), encoding="utf-8")
(pathlib.Path(env["CODEX_HOME"]) / "hooks.json").write_text(json.dumps({"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"sh -c 'exit 0'", "timeout":2}]}]}}), encoding="utf-8")
def command(argv):
    return subprocess.run(argv,cwd=workspace,env=env,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=30)
for argv in (["git","init"],["git","add",".codex"],["git","-c","user.name=Isolated","-c","user.email=isolated@example.invalid","commit","-m","isolated Hook fixture"]):
    result=command(argv)
    assert result.returncode == 0, result.stderr
lane = base / "lane-b"
assert command(["git","worktree","add","-b","lane-b",str(lane)]).returncode == 0
market = base / "marketplace"
ua = pathlib.Path(sys.argv[1]).resolve()
shutil.copytree(ua,market / "plugins/understand-anything",ignore=shutil.ignore_patterns("node_modules",".git"))
(market / ".agents/plugins").mkdir(parents=True)
(market / ".agents/plugins/marketplace.json").write_text(json.dumps({"name":"life-isolated","plugins":[{"name":"understand-anything","source":{"source":"local","path":"./plugins/understand-anything"},"policy":{"installation":"AVAILABLE","authentication":"ON_INSTALL"}}]}),encoding="utf-8")
plugin_results=[]
for argv in (["codex","plugin","marketplace","add",str(market),"--json"],["codex","plugin","add","understand-anything@life-isolated","--json"]):
    result=command(argv)
    plugin_results.append({"exit_code":result.returncode})
    if result.returncode:
        print("PLUGIN_FAILED",result.stderr[:200],flush=True)
configuration=config.read_text(encoding="utf-8")
configuration += '[projects.' + json.dumps(str(lane.resolve())) + ']\ntrust_level = "trusted"\n'
config.write_text(configuration,encoding="utf-8")
process = subprocess.Popen([shutil.which("codex"), "app-server", "--listen", "stdio://"], cwd=workspace, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
selector = selectors.DefaultSelector()
selector.register(process.stdout, selectors.EVENT_READ)
pending = b""
notifications = []

def request(identifier, method, params):
    global pending
    process.stdin.write(json.dumps({"id":identifier,"method":method,"params":params}).encode()+b"\n")
    end = time.monotonic() + 20
    while time.monotonic() < end:
        if not selector.select(.1):
            continue
        pending += os.read(process.stdout.fileno(), 65536)
        while b"\n" in pending:
            line,pending=pending.split(b"\n",1)
            row=json.loads(line)
            if row.get("id") == identifier:
                return row
            notifications.append(row)
    raise TimeoutError(method)

try:
    print("BASE", base, flush=True)
    print("INIT",json.dumps(request(1,"initialize",{"clientInfo":{"name":"life_closure_probe","version":"1"},"capabilities":{"experimentalApi":True}})),flush=True)
    process.stdin.write(b'{"method":"initialized","params":{}}\n')
    inventory=request(2,"hooks/list",{"cwds":[str(workspace)]})
    inventory=request(20,"hooks/list",{"cwds":[str(workspace),str(lane)]})
    print("HOOKS",json.dumps([{ "count":len(e["hooks"]),"sources":[h["source"] for h in e["hooks"]]} for e in inventory.get("result",{}).get("data",[])]),flush=True)
    seen=set()
    for entry in inventory.get("result",{}).get("data",[]):
        for hook in entry["hooks"]:
            if hook["key"] in seen:
                continue
            seen.add(hook["key"])
            configuration += '[hooks.state.' + json.dumps(hook["key"]) + ']\ntrusted_hash = ' + json.dumps(hook["currentHash"]) + '\n'
    config.write_text(configuration, encoding="utf-8")
    start=request(3,"thread/start",{"cwd":str(workspace),"approvalPolicy":"on-request","sandbox":"read-only","experimentalRawEvents":False})
    print("START", "result" in start,flush=True)
    if start.get("result",{}).get("thread"):
        identifier=start["result"]["thread"]["id"]
        turn=request(5,"turn/start",{"threadId":identifier,"input":[{"type":"text","text":"isolated no-effect session persistence probe"}]})
        time.sleep(.5)
        request(6,"turn/interrupt",{"threadId":identifier,"turnId":turn["result"]["turn"]["id"]})
        request(7,"hooks/list",{"cwds":[str(workspace)]})
        first_notifications=list(notifications)
        notifications.clear()
        selector.close()
        process.terminate()
        process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()
        process = subprocess.Popen([shutil.which("codex"), "app-server", "--listen", "stdio://"], cwd=lane, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        pending=b""
        request(30,"initialize",{"clientInfo":{"name":"life_closure_probe","version":"1"},"capabilities":{"experimentalApi":True}})
        process.stdin.write(b'{"method":"initialized","params":{}}\n')
        resumed=request(31,"thread/resume",{"threadId":identifier,"cwd":str(lane),"excludeTurns":True})
        print("RESUME", "result" in resumed,flush=True)
        turn2=request(32,"turn/start",{"threadId":identifier,"input":[{"type":"text","text":"isolated resumed no-effect probe"}],"cwd":str(lane)})
        time.sleep(.5)
        request(33,"turn/interrupt",{"threadId":identifier,"turnId":turn2["result"]["turn"]["id"]})
        request(34,"hooks/list",{"cwds":[str(lane)]})
        events=[]
        observer=pathlib.Path.cwd() / "integrations/codex/plugins/sulde/scripts/_hook_observer.py"
        for label, cwd, batch in (("new",workspace,first_notifications),("resumed_worktree",lane,notifications)):
            for event in batch:
                if event.get("method") == "hook/completed":
                    result=subprocess.run([sys.executable,"-B",str(observer),"--ingest-codex-notification","--workspace",str(cwd)],input=json.dumps(event),env=env,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=5)
                    run=event["params"]["run"]
                    events.append({"session_phase":label,"source":run["source"],"event":run["eventName"],"status":run["status"],"duration_ms":run.get("durationMs"),"delivery_exit":result.returncode,"notification_sha256":hashlib.sha256(json.dumps(event,sort_keys=True).encode()).hexdigest()})
        status=command([sys.executable,"-B",str(observer),"--status"])
        evidence={"schema":"life-host-isolation-v1","codex":"0.153.4","platform":"macOS","new_session":"result" in start,"resume_after_host_restart":"result" in resumed,"worktree_switch":pathlib.Path(resumed.get("result",{}).get("cwd","/unknown")).resolve()==lane.resolve(),"plugin_install":plugin_results,"third_party_hook_sha256":hashlib.sha256((ua/"hooks/hooks.json").read_bytes()).hexdigest(),"events":events,"recorder_status":json.loads(status.stdout),"model_backend":"unavailable_loopback_no_external_calls","business_tool_actions":0,"blind_spots":["third_party_post_tool_use_environment_unverified","historical_business_session_loading_unknown","no_desktop_notification_subscription_installed"]}
        pathlib.Path("/private/tmp/life-host-evidence.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")
        print(json.dumps(evidence),flush=True)
finally:
    process.terminate()
    process.wait(timeout=5)
    process.stdin.close()
    process.stdout.close()
    selector.close()
