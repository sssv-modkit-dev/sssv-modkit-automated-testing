#!/usr/bin/env python3
"""Generate cold-boot stage recipes from the calibrated menu route (no ROM needed)."""
import argparse
from collections import deque
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Button codes checked against the US decomp cheats.c; I=L, W/E=C-left/right.
UNLOCKS = {'europe': 'UDIZDUZD', 'ice': 'UDZIDEZD', 'jungle': 'UDIZDWZD',
           'desert': 'UDIZDLZD', 'parade': 'UDIZDRZD', 'secret': 'DUZIDLZD'}
BUTTON = {'U': 'DPAD_UP', 'D': 'DPAD_DOWN', 'I': 'L', 'Z': 'Z',
          'W': 'C_LEFT', 'E': 'C_RIGHT', 'L': 'DPAD_LEFT', 'R': 'DPAD_RIGHT'}
REGIONS = {'europe': range(1, 11), 'ice': range(11, 18), 'jungle': range(18, 24),
           'desert': range(24, 31), 'parade': range(31, 32), 'secret': range(32, 33)}
# Stages without the standard A -> mission brief -> START -> spawn flow.
SPECIAL_STAGES = {
    11: 'vehicle',
    17: 'no_brief_hud0',
    23: 'cutscene',
    31: 'no_brief_hud0',
    32: 'cutscene',
}


def press(button, release=30):
    return {'action': 'press', 'buttons': [button], 'frames': 3, 'release_frames': release}


def menu_path(target, available):
    """BFS over the unlocked selector ring, minimizing distinct button presses."""
    if target not in available:
        raise ValueError('target is locked')
    ring = sorted(available)
    queue = deque([(1, [])])
    seen = {1}
    while queue:
        current, path = queue.popleft()
        if current == target:
            return path
        idx = ring.index(current)
        for delta, button in [(1, 'DPAD_RIGHT'), (-1, 'DPAD_LEFT')]:
            dest = ring[(idx + delta) % len(ring)]
            if dest not in seen:
                seen.add(dest)
                queue.append((dest, path + [button]))
    raise ValueError('no selector path')


def make_recipe(stage, template, all_unlocked=False, diagnostic=False):
    if type(stage) is not int or not 1 <= stage <= 32:
        raise ValueError('stage must be 1..32')
    regions = list(REGIONS) if all_unlocked else [
        region for region, ids in REGIONS.items() if region == 'europe' or stage in ids]
    available = {i for region in regions for i in REGIONS[region]}
    route = menu_path(stage, available)
    steps = copy.deepcopy(template['steps'])
    cut = next(i for i, s in enumerate(steps) if s.get('label') == 's4_stage_menu')
    prefix = steps[:cut + 1]
    # Europe code already occurs in the calibrated template. Add other unlocks
    # immediately after it; each is a toggle, so never enter Europe twice.
    at = next(i for i, s in enumerate(prefix) if s.get('label') == 's0_bank_after_unlock')
    extra = [press(BUTTON[c], 20) for region in regions if region != 'europe'
             for c in UNLOCKS[region]]
    prefix[at:at] = extra
    # Keep the original capture's two neutral frames without writing redundant PNGs.
    prefix = [{'action': 'wait', 'frames': 2} if s['action'] == 'capture' else s
              for s in prefix]
    steps = prefix + [press(button) for button in route]
    if diagnostic:
        steps.append({'action': 'capture', 'label': 'stage_selected'})
    special_kind = SPECIAL_STAGES.get(stage)
    route_info = {
        'target_stage_id': stage,
        'unlocks': regions,
        'selector_start_stage_id': 1,
        'selector_inputs': route,
        'stage_flow': 'special' if special_kind else 'standard',
        'validation': 'source_derived_not_game_verified',
    }
    if special_kind:
        route_info['special_kind'] = special_kind
        steps += [press('A', 240), {'action': 'capture', 'label': 'post_select'},
                  press('A', 300), {'action': 'capture', 'label': 'spawn'}]
        notes = ('Source-derived selector path for a special stage using calibrated conservative bootstrap. '
                 'Special stages (11, 17, 23, 31, 32) skip the standard mission brief and avoid START '
                 '(which can pause). Generated does not mean visually verified; capture_pass does not '
                 'establish stage or animal correctness.')
    else:
        steps += [press('A', 240), {'action': 'capture', 'label': 'mission_brief'},
                  press('START', 300), {'action': 'capture', 'label': 'spawn'}]
        notes = ('Source-derived selector path using calibrated conservative bootstrap. '
                 'Generated does not mean visually verified. Inspect mission brief and spawn; '
                 'capture_pass does not establish stage or animal correctness.')
    return {'version': 1, 'ready': True, 'cold_boot_only': True,
            'name': f'Cold boot to stage {stage:02d}',
            'notes': notes,
            'route': route_info,
            'steps': steps}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--stage', nargs='+', type=int)
    group.add_argument('--all', action='store_true')
    ap.add_argument('--out-dir', type=Path, required=True)
    ap.add_argument('--all-unlocked', action='store_true')
    ap.add_argument('--diagnostic', action='store_true')
    args = ap.parse_args()
    template = json.loads((ROOT / 'recipes/fat-bear-mountain.json').read_text())
    recipes = [(sid, make_recipe(sid, template, args.all_unlocked, args.diagnostic))
               for sid in (range(1, 33) if args.all else args.stage)]
    paths = [(args.out_dir / f'stage-{sid:02d}.json', recipe) for sid, recipe in recipes]
    if len({path for path, _ in paths}) != len(paths):
        raise ValueError('duplicate requested stages')
    for path, _ in paths:
        if path.exists():
            raise FileExistsError(f'Refusing to overwrite {path}')
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for path, recipe in paths:
        path.write_text(json.dumps(recipe, indent=2) + '\n')
    print(f'Generated {len(recipes)} recipes in {args.out_dir}; scene verification is separate.')


if __name__ == '__main__':
    main()
