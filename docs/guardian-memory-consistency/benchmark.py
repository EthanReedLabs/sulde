"""Same-interpreter, alternating baseline/candidate pure read hot-path samples."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PROBE = r'''
import json, sys, time, statistics
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'scripts/kb'))
from intent_guardian import default_contract, normalize_hook_event, evaluate_event
contract=default_contract(intent_id='benchmark',objective='Read task state',acceptance_criteria=['Read only'],
    workspace=Path(sys.argv[2]),mode='enforce',confirmed_by='human')
payload={'client':'codex','session_id':'benchmark','tool_name':'Bash','tool_input':{'command':'pwd'},'cwd':sys.argv[2]}
samples=[]
for i in range(600):
    start=time.perf_counter_ns()
    event=normalize_hook_event(payload,phase='started',provider='codex')
    decision=evaluate_event(contract,event)
    if decision.action != 'allow': raise RuntimeError(decision.reason)
    elapsed=(time.perf_counter_ns()-start)/1e6
    if i>=100:samples.append(elapsed)
samples.sort()
print(json.dumps({'samples':len(samples),'p50_ms':statistics.median(samples),'p95_ms':samples[int(len(samples)*.95)-1]}))
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    from run_checks import source_digest, OUT
    before=source_digest(semantic=True)
    samples=[]
    with tempfile.TemporaryDirectory(prefix='sulde-memory-consistency-bench-',dir='/private/tmp') as tmp:
        env={k:v for k,v in os.environ.items() if not k.startswith(('SULDE_','CODEX_','CLAUDE_'))}
        env.update(PYTHONDONTWRITEBYTECODE='1',SULDE_KB_HOME=tmp,TMPDIR=tmp)
        for _ in range(5):
            for label,source in [('baseline',args.baseline),('candidate',root)]:
                result=subprocess.run([sys.executable,'-B','-c',PROBE,str(source),tmp],env=env,
                    capture_output=True,text=True,encoding='utf-8',errors='replace',check=True)
                samples.append({'label':label,**json.loads(result.stdout)})
    evidence={'schema':'guardian-read-benchmark-v1','python':sys.version,'source_sha256':before,
        'source_unchanged':before==source_digest(semantic=True),'measurement':'normalize + evaluate, read only; excludes process/Hook startup',
        'baseline_head':subprocess.check_output(['git','-C',str(args.baseline),'rev-parse','HEAD'],text=True,encoding='utf-8',errors='replace').strip(),
        'samples':samples}
    OUT.mkdir(parents=True,exist_ok=True)
    target=OUT/('benchmark-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
    target.write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps({'path':str(target.relative_to(root)),**evidence},indent=2))

if __name__=='__main__': main()
