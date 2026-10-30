import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import harness
import inspection as ins


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rom = self.root / 'rom.z64'
        self.rom.write_bytes(bytes.fromhex('80371240') + b'synthetic')
        self.session = self.root / 'session'
        ins.prepare(self.session, self.rom, 5)

    def cold_run(self, directory=None):
        run = directory or self.root / 'cold'
        run.mkdir(parents=True)
        state = run / 'inspection_spawn.st'
        state.write_bytes(b'synthetic native state')
        ins.write(str(state) + '.json', {'rom_sha1': harness.digest(self.rom),
                  'state_sha1': harness.digest(state), 'origin': 'cold_boot', 'source_state': None})
        ins.write(run / 'plan.json', {'rom_sha1': harness.digest(self.rom), 'state': None,
                  'recipe': ins.read(self.session / 'bootstrap.json')})
        ins.write(run / 'summary.json', {'status': 'capture_complete', 'capture_pass': True,
                  'exit_code': 0, 'core_errors': [], 'saved_states': [str(state.resolve())],
                  'elapsed_seconds': 100, 'semantic_pass': None})
        return run, state

    def test_recipes_and_first_run(self):
        for name in ('bootstrap', 'zoom', 'orbit', 'movement'):
            harness.compile_recipe(ins.read(self.session / (name + '.json')))
        plan = ins.run_session(self.session, dry_run=True)
        self.assertEqual(plan['kind'], 'cold_boot')
        self.assertNotIn('--state', plan['command'])
        self.assertIsNone(plan['scene_review'])
        for kwargs in ({'timeout': 0}, {'preset': 'unknown'}):
            with self.assertRaises(ValueError):
                ins.run_session(self.session, dry_run=True, **kwargs)
        with self.assertRaises(ValueError):
            ins.prepare(self.session, self.rom, 5)

    def test_adopt_then_replay(self):
        run, state = self.cold_run()
        ins.adopt(self.session, run)
        plan = ins.run_session(self.session, preset='movement', dry_run=True)
        self.assertEqual(plan['kind'], 'replay')
        self.assertEqual(plan['command'][-2:], ['--state', str(state.resolve())])
        self.assertIsNone(plan['scene_review'])
        with self.assertRaises(ValueError):
            ins.adopt(self.session, run)

    def test_changed_rom_recipe_or_checkpoint_refused(self):
        run, state = self.cold_run()
        ins.adopt(self.session, run)
        original = self.rom.read_bytes()
        self.rom.write_bytes(original + b'changed')
        with self.assertRaisesRegex(ValueError, 'ROM changed'):
            ins.run_session(self.session, dry_run=True)
        self.rom.write_bytes(original)
        recipe = self.session / 'zoom.json'; original_recipe = recipe.read_text()
        data = json.loads(original_recipe); data['steps'][0]['frames'] = 99
        ins.write(recipe, data)
        with self.assertRaisesRegex(ValueError, 'recipe changed'):
            ins.run_session(self.session, dry_run=True)
        recipe.write_text(original_recipe)
        state.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'checkpoint changed'):
            ins.run_session(self.session, dry_run=True)

    def test_rejects_failed_wrong_stage_and_loaded_run(self):
        run, state = self.cold_run()
        plan_path = run / 'plan.json'; result_path = run / 'summary.json'
        plan = ins.read(plan_path); result = ins.read(result_path)
        for field, value in [('capture_pass', False), ('exit_code', 1),
                             ('core_errors', ['error']), ('saved_states', [])]:
            ins.write(result_path, dict(result, **{field: value}))
            with self.assertRaises(ValueError): ins.adopt(self.session, run)
        ins.write(result_path, result)
        for changed in [dict(plan, state='loaded.st'), dict(plan, rom_sha1='wrong'),
                        dict(plan, recipe={'route': {'target_stage_id': 7}})]:
            ins.write(plan_path, changed)
            with self.assertRaises(ValueError): ins.adopt(self.session, run)
        ins.write(plan_path, plan)
        meta = ins.read(str(state) + '.json'); meta['origin'] = 'loaded_state'
        ins.write(str(state) + '.json', meta)
        with self.assertRaises(ValueError): ins.adopt(self.session, run)

    def test_rejects_unverified_state_and_path_escape(self):
        run, state = self.cold_run()
        Path(str(state) + '.json').unlink()
        with self.assertRaises(ValueError): ins.adopt(self.session, run)
        with self.assertRaises(ValueError): ins.adopt(self.session, run, '../escape')

    def test_debug_state_separate_and_explicit(self):
        run, state = self.cold_run(); ins.adopt(self.session, run)
        debug = self.root / 'debug.st'; debug.write_bytes(b'debug camera')
        meta = {'rom_sha1': harness.digest(self.rom), 'state_sha1': harness.digest(debug),
                'origin': 'derived_camera_debug_state', 'source_state_sha1': 'wrong',
                'edits': [{'purpose': 'synthetic camera edit'}]}
        ins.write(str(debug) + '.json', meta)
        with self.assertRaises(ValueError): ins.register_debug(self.session, debug)
        meta['source_state_sha1'] = harness.digest(state)
        ins.write(str(debug) + '.json', meta); ins.register_debug(self.session, debug)
        self.assertEqual(ins.run_session(self.session, dry_run=True)['command'][-1], str(state.resolve()))
        self.assertEqual(ins.run_session(self.session, 'orbit', True, dry_run=True)['command'][-1], str(debug.resolve()))
        with self.assertRaises(ValueError): ins.run_session(self.session, 'movement', True, dry_run=True)

    def test_cold_boot_registers_and_replay_records_evidence(self):
        run, state = self.cold_run(self.session / 'captures' / 'synthetic')
        process = mock.Mock(returncode=0, stdout='Run: ' + str(run) + '\n', stderr='')
        with mock.patch.object(ins.subprocess, 'run', return_value=process):
            result = ins.run_session(self.session)
        self.assertEqual(result['kind'], 'cold_boot')
        self.assertEqual(ins.read(self.session / 'session.json')['checkpoint']['sha1'], harness.digest(state))
        summary = ins.read(run / 'summary.json'); summary['state_loaded'] = True
        ins.write(run / 'summary.json', summary)
        with mock.patch.object(ins.subprocess, 'run', return_value=process) as call:
            result = ins.run_session(self.session)
        self.assertEqual(result['kind'], 'replay')
        self.assertIn('--state', call.call_args[0][0])
        self.assertEqual(len(ins.read(self.session / 'session.json')['history']), 2)
        self.assertIsNone(ins.read(self.session / 'session.json')['scene_review'])

    def test_harness_failure_preserves_session(self):
        before = (self.session / 'session.json').read_bytes()
        process = mock.Mock(returncode=1, stdout='failed', stderr='core error')
        with mock.patch.object(ins.subprocess, 'run', return_value=process):
            with self.assertRaisesRegex(ValueError, 'harness failed'):
                ins.run_session(self.session)
        self.assertEqual((self.session / 'session.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
