"""Record isolated candidate entrypoints, never promote/install production."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reviewed-head', required=True)
    parser.add_argument('--revision', choices=('r20', 'r22', 'r23'), default='r22')
    parser.add_argument('--behavior-base')
    args = parser.parse_args()
    os.umask(0o077)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    run = ROOT / ('.codex-agent/layered-' + args.revision) / stamp
    run.mkdir(parents=True, mode=0o700)
    # Ordinary write probes cannot live below protected .codex-agent ancestors.
    # Keep audit logs in the task, but execute only in a fresh approved temp root.
    candidate_home = Path('/private/tmp') / ('sulde-s3c-' + args.revision + '-' + stamp)
    if candidate_home.exists() or candidate_home.is_symlink():
        raise RuntimeError('candidate root already exists; refuse reuse')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
    # Only the official OS-isolated runner may assert this proof. This helper
    # leaves the candidate's own isolation check enabled.
    env.pop('SULDE_ISOLATED_TEST_RUN_ID', None)
    facts = {'run_id': stamp, 'scope': 'L0-mapping-and-L1-isolated-only', 'phases': [],
             'real_scheduler': 'pending_host', 'native_maintenance': 'pending_host'}
    facts['candidate_home'] = str(candidate_home)
    facts['reviewed_source'] = args.reviewed_head
    facts['version_scope'] = 'development-candidate-not-production-publication'
    if args.revision == 'r23':
        if not args.behavior_base:
            raise RuntimeError('r23 requires the prior tested behavior baseline')
        facts['version_scope'] = 'unique-publication-candidate-not-installed'
    candidate_id = args.revision + '-posix'
    observed = {
        'deployment': Path('/Users/eric/.sulde/data/kb/deployment-generation.json'),
        'codex_config': Path('/Users/eric/.codex/config.toml'),
        'claude_registry': Path('/Users/eric/.claude/plugins/installed_plugins.json'),
        'claude_marketplaces': Path('/Users/eric/.claude/plugins/known_marketplaces.json'),
    }
    facts['production_file_hashes_before'] = {k: digest(p) for k, p in observed.items()}

    def call(label, argv, timeout=600):
        started = time.monotonic()
        print('START ' + label, flush=True)
        with (run / (label + '.stdout')).open('x', encoding='utf-8') as out, (run / (label + '.stderr')).open('x', encoding='utf-8') as err:
            result = subprocess.run(argv, cwd=ROOT, env=env, stdout=out, stderr=err,
                                    timeout=timeout, check=False)
        fact = {'phase': label, 'argv': argv, 'exit_code': result.returncode,
                'seconds': round(time.monotonic() - started, 3)}
        facts['phases'].append(fact)
        print(json.dumps(fact), flush=True)
        (run / 'result.json').write_text(json.dumps(facts, indent=2), encoding='utf-8')
        if result.returncode:
            raise RuntimeError(label + ' failed; inspect retained stdout/stderr')

    code = 1
    try:
        call('source-head', ['git', 'rev-parse', 'HEAD'])
        call('source-clean', ['git', 'status', '--porcelain', '--untracked-files=no'])
        if (run / 'source-clean.stdout').read_text(encoding='utf-8').strip():
            raise RuntimeError('tracked source is not frozen')
        call('source-equivalence', ['git', 'diff', '--exit-code', args.reviewed_head, 'HEAD', '--',
             '.', ':(exclude)docs/guardian-update-continuity/**'])
        if args.behavior_base:
            manifests = ('.claude-plugin/plugin.json',
                         'integrations/codex/plugins/sulde/.codex-plugin/plugin.json')
            call('behavior-equivalence', ['git', 'diff', '--exit-code', args.behavior_base,
                 'HEAD', '--', '.', ':(exclude)docs/guardian-update-continuity/**',
                 *[':(exclude)' + name for name in manifests]])
            changes = {}
            for name in manifests:
                old = json.loads(subprocess.check_output(
                    ['git', 'show', args.behavior_base + ':' + name], cwd=ROOT, env=env))
                new = json.loads((ROOT / name).read_text(encoding='utf-8'))
                versions = {'old': old.pop('version'), 'new': new.pop('version')}
                if old != new or versions['old'] == versions['new']:
                    raise RuntimeError('manifest must change only version: ' + name)
                changes[name] = versions
            facts['behavior_equivalence'] = {'base': args.behavior_base,
                'product_code_tests_dependencies_unchanged': True,
                'manifest_version_only_changes': changes,
                'excluded_task_harness': 'docs/guardian-update-continuity/**'}
        codex = shutil.which('codex')
        claude = shutil.which('claude')
        if not codex or not claude:
            raise RuntimeError('required installed host CLI is unavailable')
        call('codex-version', [codex, '--version'])
        call('claude-version', [claude, '--version'])
        command = [sys.executable, '-B', str(ROOT / 'scripts/release/candidate_codex_plugin.py'),
                   '--candidate-home', str(candidate_home), '--codex', codex, '--json']
        call('codex-prepare', command + ['prepare', '--candidate-id', candidate_id])
        call('codex-verify', command + ['verify', candidate_id], timeout=900)
        call('claude-stage', [sys.executable, '-B', str(ROOT / 'scripts/release/stage_plugin.py'),
                             '--target', 'claude', '--output', str(run / 'claude-artifact')])
        call('claude-validate', [claude, 'plugin', 'validate',
             str(run / 'claude-artifact/.claude-plugin/plugin.json'), '--json', '--strict'])
        validation = json.loads((run / 'claude-validate.stdout').read_text(encoding='utf-8'))
        if validation.get('success') is not True or validation.get('strict') is not True:
            raise RuntimeError('Claude strict validation did not prove success')
        artifact = run / 'claude-artifact'
        files = {}
        for path in sorted(artifact.rglob('*')):
            if path.is_symlink() or path.name == '__pycache__' or path.suffix == '.pyc':
                raise RuntimeError('unexpected mutable/link artifact entry: ' + str(path))
            if path.is_file():
                files[str(path.relative_to(artifact))] = digest(path)
        identity = run / 'claude-identity.json'
        identity.write_text(json.dumps({'scope': 'artifact-only-not-production-live',
                            'files': files}, sort_keys=True, indent=2), encoding='utf-8')
        facts['claude_identity_sha256'] = digest(identity)
        facts['claude_file_count'] = len(files)
        facts['status'] = 'isolated-candidate-entrypoints-passed-not-installed'
        code = 0
    except Exception as error:
        facts['status'] = 'incomplete'
        facts['error'] = str(error)
    finally:
        facts['production_file_hashes_after'] = {k: digest(p) for k, p in observed.items()}
        facts['production_files_equal'] = facts['production_file_hashes_before'] == facts['production_file_hashes_after']
        if not facts['production_files_equal']:
            facts['status'] = 'production-observation-drift-investigate'
            code = 1
        (run / 'result.json').write_text(json.dumps(facts, indent=2), encoding='utf-8')
        hashes = {p.name: digest(p) for p in run.iterdir() if p.is_file()}
        (run / 'manifest.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
        print(json.dumps({'run': str(run), 'status': facts['status'], 'exit_code': code}), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
