import json
from pathlib import Path
import unittest

import harness
import stage_routes as routes


class StageRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = json.loads((Path(__file__).parent / 'recipes/fat-bear-mountain.json').read_text())

    def test_all_targets_reached_on_unlocked_ring(self):
        for all_unlocked in (False, True):
            for sid in range(1, 33):
                recipe = routes.make_recipe(sid, self.template, all_unlocked)
                ring = sorted(i for region in recipe['route']['unlocks'] for i in routes.REGIONS[region])
                pos = ring.index(1)
                for button in recipe['route']['selector_inputs']:
                    pos = (pos + (1 if button == 'DPAD_RIGHT' else -1)) % len(ring)
                self.assertEqual(ring[pos], sid)
                self.assertLessEqual(len(recipe['route']['selector_inputs']), len(ring) // 2)
                events, end = harness.compile_recipe(recipe)
                self.assertEqual([e['label'] for e in events if e['action'] == 'capture'],
                                 ['mission_brief', 'spawn'])
                self.assertTrue(recipe['cold_boot_only'])

    def test_known_selector_offsets_and_wrap(self):
        self.assertEqual(routes.make_recipe(3, self.template)['route']['selector_inputs'], ['DPAD_RIGHT'] * 2)
        self.assertEqual(routes.make_recipe(6, self.template)['route']['selector_inputs'], ['DPAD_RIGHT'] * 5)
        self.assertEqual(routes.make_recipe(32, self.template, True)['route']['selector_inputs'], ['DPAD_LEFT'])

    def test_unlocks_once_and_invalid_target(self):
        recipe = routes.make_recipe(11, self.template)
        self.assertEqual(recipe['route']['unlocks'], ['europe', 'ice'])
        self.assertEqual(sum(s.get('buttons') == ['C_RIGHT'] for s in recipe['steps']), 1)
        for sid in (0, 33, True):
            with self.assertRaises(ValueError):
                routes.make_recipe(sid, self.template)

    def test_calibrated_bootstrap_button_schedule_preserved(self):
        original, _ = harness.compile_recipe(self.template)
        recipe = routes.make_recipe(6, self.template)
        generated, _ = harness.compile_recipe(recipe)
        boundary = next(e['frame'] for e in original if e.get('label') == 's4_stage_menu')
        def inputs(events):
            return [e for e in events if e['frame'] <= boundary and e['action'] in ('down', 'up')]
        self.assertEqual(inputs(original), inputs(generated))


if __name__ == '__main__':
    unittest.main()
