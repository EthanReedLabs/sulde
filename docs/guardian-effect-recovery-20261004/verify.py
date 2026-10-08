"""Archive bounded unittest output; no production actions or mutable evidence."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

root = Path(__file__).resolve().parents[2]
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
out = Path('/Volumes/Optimus/Sulde/tasks/guardian-effect-recovery-20261004') / (stamp + '-' + sys.argv[1])
out.mkdir(parents=True, exist_ok=False)
env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', SULDE_NOTIFY='off')
args = [sys.executable, '-B', '-m', 'unittest', *sys.argv[2:]]
p = subprocess.run(args, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
(out / 'unittest.log').write_bytes(p.stdout)
files = ['scripts/kb/intervention.py', 'scripts/kb/intent_guardian_parts/resources.py',
         'scripts/kb/intent_guardian_parts/policy.py', 'scripts/kb/intent_guardian_parts/approvals.py',
         'scripts/kb/intent_guardian_parts/intervention_control.py',
         'scripts/kb/intent_guardian_parts/state.py', 'scripts/kb/intent_guardian.py',
         'scripts/kb/intent-guardian.py', 'tests/test_effect_recovery_20261004.py',
         'docs/guardian-effect-recovery-20261004/verify.py']
data = dict(argv=args, exit_code=p.returncode, head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
            input_sha256={f:hashlib.sha256((root/f).read_bytes()).hexdigest() for f in files},
            output_sha256=hashlib.sha256(p.stdout).hexdigest())
(out / 'evidence.json').write_text(json.dumps(data,indent=2)+'\n', encoding='utf-8')
print(p.stdout.decode(errors='replace'))
print('EVIDENCE:', out)
sys.exit(p.returncode)
