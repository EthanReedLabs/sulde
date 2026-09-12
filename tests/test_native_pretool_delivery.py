"""A staged candidate, real CLI host, real unified executor and real deny Hook."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/release'))
import candidate_codex_plugin as candidate


@unittest.skipIf(os.name == 'nt', 'Native Windows acceptance is Windows-owned')
@unittest.skipUnless(shutil.which('codex'), 'Native Codex CLI required')
class NativePreToolDeliveryTests(unittest.TestCase):
    def test_staged_artifact_native_positive_scope_negative_and_v2_proof(self):
        with tempfile.TemporaryDirectory(prefix='sulde-native-pretool-') as temporary:
            slot = Path(temporary).resolve()
            installer = candidate.installer
            codex = shutil.which('codex')
            prepared = installer._stage_artifact(slot / 'artifact', platform='posix', runner=installer.run_command)
            generation = prepared.descriptor['delivery_generation']
            env = candidate._candidate_environment(slot, codex, candidate._python_identity(Path(sys.executable)))
            runner = candidate._bound_runner(env)
            externally_isolated = bool(os.environ.get('SULDE_ISOLATED_TEST_RUN_ID'))
            with candidate._process_environment(env):
                installed = installer._registry_add(codex, prepared.marketplace, runner,
                                                   expected_version=generation['plugin_version'])
                kb = Path(env['SULDE_KB_HOME'])
                installer._install_launchers(installed, kb, runner, platform='posix')
                installer._smoke_installed(installed, kb, codex=codex,
                    expected_tree_sha256=prepared.plugin_tree_sha256, runner=runner)
                proof = candidate._verify_real_preexecution_chain(installed, kb_home=kb,
                    environment=env, runner=runner, expected_artifact_generation=generation['generation'],
                    externally_isolated=externally_isolated)
            self.assertEqual(proof['transport'], 'codex-cli-app-server')
            self.assertEqual(proof['artifact_generation'], generation['generation'])
            self.assertTrue(proof['positive_executed'])
            self.assertTrue(proof['outside_plan_write_executed'])
            self.assertTrue(proof['destructive_pre_denied'])
            self.assertTrue(proof['marker_absent'])
            print('NATIVE_PRETOOL_EVIDENCE=' + json.dumps(proof, sort_keys=True), flush=True)
