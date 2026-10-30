#!/usr/bin/env python3
"""Build-bound inspection sessions: cold boot once, replay matching checkpoints."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import harness
import stage_routes

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def recipe_hash(recipe):
    return hashlib.sha1(json.dumps(recipe, sort_keys=True).encode()).hexdigest()


def replay_recipe(preset):
    steps = [{'action': 'wait', 'frames': 30}]
    if preset in ('zoom', 'orbit'):
        steps += [stage_routes.press('C_DOWN', 45), stage_routes.press('C_DOWN', 45),
                  {'action': 'capture', 'label': 'close'}]
    if preset == 'orbit':
        for i in range(1, 5):
            steps += [stage_routes.press('C_LEFT', 45),
                      {'action': 'capture', 'label': f'orbit_attempt_{i}'}]
    if preset == 'movement':
        for button, frames, label in [('UP', 60, 'forward'), ('LEFT', 30, 'turn'),
                                      ('UP', 60, 'forward_again')]:
            steps += [{'action': 'press', 'buttons': [button], 'frames': frames,
                       'release_frames': 1}, {'action': 'capture', 'label': label}]
    return {'version': 1, 'ready': True, 'cold_boot_only': False,
            'name': 'Inspection: ' + preset,
            'notes': 'Camera input is mode-limited. Capture success does not verify '
                     'the scene, orbit, geometry, movement or collision.', 'steps': steps}


def prepare(directory, rom, stage):
    directory, rom = Path(directory).resolve(), Path(rom).resolve()
    if directory.exists():
        raise ValueError('session directory already exists; use a new directory')
    if rom.read_bytes()[:4] != bytes.fromhex('80371240'):
        raise ValueError('expected a big-endian .z64 ROM')
    template = read(ROOT / 'recipes/fat-bear-mountain.json')
    bootstrap = stage_routes.make_recipe(stage, template)
    bootstrap['steps'].append({'action': 'save_state', 'label': 'inspection_spawn'})
    recipes = {'bootstrap': bootstrap}
    recipes.update({p: replay_recipe(p) for p in ('zoom', 'orbit', 'movement')})
    for recipe in recipes.values():
        harness.compile_recipe(recipe)
    session = {'version': 1, 'rom': str(rom), 'rom_sha1': harness.digest(rom),
               'stage': stage, 'recipes': {k: recipe_hash(v) for k, v in recipes.items()},
               'checkpoint': None, 'debug_checkpoint': None, 'history': [],
               'scene_review': None}
    directory.mkdir(parents=True)
    for name, recipe in recipes.items():
        write(directory / (name + '.json'), recipe)
    write(directory / 'session.json', session)
    return session


def load_session(directory):
    directory = Path(directory).resolve()
    session = read(directory / 'session.json')
    if session['version'] != 1 or harness.digest(session['rom']) != session['rom_sha1']:
        raise ValueError('ROM changed: create a fresh session and cold-boot checkpoint')
    for name, expected in session['recipes'].items():
        if recipe_hash(read(directory / (name + '.json'))) != expected:
            raise ValueError('session recipe changed: create a new session')
    return directory, session


def checkpoint_record(state, rom):
    state = Path(state).resolve()
    if harness.validate_state(state, rom) != 'sha1_manifest_matches':
        raise ValueError('checkpoint requires a matching ROM/state SHA1 sidecar')
    return {'path': str(state), 'sha1': harness.digest(state)}


def verify_checkpoint(record, rom):
    if harness.digest(record['path']) != record['sha1']:
        raise ValueError('registered checkpoint changed')
    checkpoint_record(record['path'], rom)


def adopt(directory, run, label='inspection_spawn'):
    directory, session = load_session(directory)
    if session['checkpoint'] is not None:
        raise ValueError('session already has a checkpoint')
    run = Path(run).resolve()
    plan, result = read(run / 'plan.json'), read(run / 'summary.json')
    if (plan['rom_sha1'] != session['rom_sha1'] or plan.get('state') is not None
            or plan['recipe'].get('route', {}).get('target_stage_id') != session['stage']
            or result.get('capture_pass') is not True or result.get('exit_code') != 0
            or result.get('status') != 'capture_complete' or result.get('core_errors')):
        raise ValueError('requires a successful cold boot for this exact ROM and stage')
    harness.label(label)
    state = run / (label + '.st')
    saved = {str(Path(p).resolve()) for p in result.get('saved_states', [])}
    if str(state.resolve()) not in saved:
        raise ValueError('checkpoint was not saved by the supplied run')
    record = checkpoint_record(state, session['rom'])
    meta = read(str(state) + '.json')
    if meta.get('origin') != 'cold_boot' or meta.get('source_state') is not None:
        raise ValueError('primary checkpoint must originate from a cold boot')
    session['checkpoint'] = record
    session['history'].append({'kind': 'cold_boot', 'run': str(run),
                               'recipe_sha1': recipe_hash(plan['recipe']),
                               'elapsed_seconds': result.get('elapsed_seconds')})
    write(directory / 'session.json', session)
    return session


def register_debug(directory, state):
    directory, session = load_session(directory)
    if session['checkpoint'] is None:
        raise ValueError('register the cold-boot checkpoint first')
    verify_checkpoint(session['checkpoint'], session['rom'])
    record = checkpoint_record(state, session['rom'])
    meta = read(str(Path(state).resolve()) + '.json')
    if (meta.get('origin') != 'derived_camera_debug_state'
            or meta.get('source_state_sha1') != session['checkpoint']['sha1']
            or not meta.get('edits')):
        raise ValueError('debug state must record derivation from this primary checkpoint')
    if session['debug_checkpoint'] is not None:
        raise ValueError('session already has a debug checkpoint')
    record['scope'] = 'explicit debug-state replay, not ordinary gameplay validation'
    session['debug_checkpoint'] = record
    write(directory / 'session.json', session)


def run_session(directory, preset='zoom', debug=False, timeout=300, dry_run=False):
    if preset not in ('zoom', 'orbit', 'movement') or type(timeout) is not int or timeout < 1:
        raise ValueError('requires a known preset and positive timeout')
    directory, session = load_session(directory)
    if debug and preset != 'orbit':
        raise ValueError('debug checkpoint is restricted to the orbit inspection preset')
    checkpoint = session['debug_checkpoint' if debug else 'checkpoint']
    if debug and checkpoint is None:
        raise ValueError('no debug checkpoint registered')
    mode = 'replay' if checkpoint else 'cold_boot'
    recipe = preset if checkpoint else 'bootstrap'
    if checkpoint:
        verify_checkpoint(checkpoint, session['rom'])
    command = [sys.executable, str(ROOT / 'harness.py'), 'recipe',
               str(directory / (recipe + '.json')), '--rom', session['rom'],
               '--timeout', str(timeout)]
    if checkpoint:
        command += ['--state', checkpoint['path']]
    if dry_run:
        return {'kind': mode, 'debug': debug, 'command': command,
                'scene_review': session['scene_review']}
    env = dict(os.environ, SSSV_TEST_DIR=str(directory))
    result = subprocess.run(command, env=env, text=True, capture_output=True)
    runs = [line[5:] for line in result.stdout.splitlines() if line.startswith('Run: ')]
    if result.returncode or len(runs) != 1:
        raise ValueError('harness failed; retained run output:\n' + result.stdout + result.stderr)
    run = Path(runs[0]).resolve()
    if directory / 'captures' not in run.parents:
        raise ValueError('harness returned a run outside this session')
    summary = read(run / 'summary.json')
    if mode == 'cold_boot':
        adopt(directory, run)
    else:
        if (summary.get('capture_pass') is not True or summary.get('core_errors')
                or summary.get('state_loaded') is not True):
            raise ValueError('replay did not complete with a loaded checkpoint: ' + str(run))
        session['history'].append({'kind': mode, 'debug': debug, 'preset': preset,
                                   'run': str(run), 'elapsed_seconds': summary['elapsed_seconds']})
        write(directory / 'session.json', session)
    return {'kind': mode, 'debug': debug, 'run': str(run),
            'elapsed_seconds': summary['elapsed_seconds'],
            'capture_pass': summary['capture_pass'], 'semantic_pass': summary.get('semantic_pass'),
            'next': 'Review the scene, then run again for checkpoint replay.'}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    commands = ap.add_subparsers(dest='action', required=True)
    init = commands.add_parser('prepare'); init.add_argument('--rom', required=True)
    init.add_argument('--stage', type=int, required=True)
    attach = commands.add_parser('adopt'); attach.add_argument('--run', required=True)
    attach.add_argument('--label', default='inspection_spawn')
    debug = commands.add_parser('register-debug'); debug.add_argument('--state', required=True)
    run = commands.add_parser('run'); run.add_argument('--preset', choices=['zoom', 'orbit', 'movement'], default='zoom')
    run.add_argument('--debug', action='store_true'); run.add_argument('--dry-run', action='store_true')
    run.add_argument('--timeout', type=int, default=300)
    review = commands.add_parser('review'); review.add_argument('--note', required=True)
    for command in (init, attach, debug, run, review):
        command.add_argument('--session', required=True)
    args = ap.parse_args(argv)
    try:
        if args.action == 'prepare':
            prepare(args.session, args.rom, args.stage)
            output = {'session': str(Path(args.session).resolve()), 'next': 'run'}
        elif args.action == 'adopt':
            adopt(args.session, args.run, args.label); output = {'checkpoint': 'registered'}
        elif args.action == 'register-debug':
            register_debug(args.session, args.state); output = {'debug_checkpoint': 'registered'}
        elif args.action == 'review':
            directory, session = load_session(args.session)
            if not session['checkpoint'] or not args.note.strip():
                raise ValueError('review requires a cold-boot checkpoint and a nonempty note')
            session['scene_review'] = {'note': args.note, 'scope': 'manual observation, not automated semantic validation'}
            write(directory / 'session.json', session); output = session['scene_review']
        else:
            output = run_session(args.session, args.preset, args.debug, args.timeout, args.dry_run)
        print(json.dumps(output, indent=2))
        return 0
    except (ValueError, KeyError, OSError, TypeError) as exc:
        ap.error(str(exc))


if __name__ == '__main__':
    sys.exit(main())
