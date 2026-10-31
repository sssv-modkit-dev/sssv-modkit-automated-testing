# Inspection sessions

An inspection session keeps the recipes, checkpoints, and run history for one
ROM build and stage together. Cold-boot the build once, check the scene, then
replay a saved checkpoint for camera and movement checks. Sessions use the
harness on its own; they do not edit ROMs or states.

## Prepare once, then replay

Run these commands on the harness's Linux/WSL backend. Keep sessions under
`captures/`, where local paths, hashes, states, and results are ignored by Git.

```sh
python3 inspection.py prepare --session captures/fox-v1 --stage 5 --rom /path/to/build.z64
python3 inspection.py run --session captures/fox-v1
# Inspect mission_brief.png and spawn.png in the reported run directory.
python3 inspection.py review --session captures/fox-v1 --note 'Describe what you actually observed.'
python3 inspection.py run --session captures/fox-v1 --preset zoom
python3 inspection.py run --session captures/fox-v1 --preset movement
```

The first `run` cold-boots the game and saves `inspection_spawn.st`. It registers
the checkpoint after the run succeeds and its provenance checks pass. Later
runs use that checkpoint and the requested preset. `--dry-run` shows the command
without launching an emulator; `--timeout` sets the harness timeout in seconds.
Run one inspection at a time. Concurrent emulators can interfere with input,
the display, and session updates.

The session directory contains `session.json`, four generated recipe JSON files,
and per-run captures, plans, logs, result/summary JSON and state sidecars. History
records the source cold boot and elapsed replay times. Manual review notes are
stored separately; they do not change `semantic_pass`.

The session records the ROM SHA1, recipe contents, and registered checkpoint
SHA1. It refuses to run if any have changed, if the checkpoint is missing, or
if the ROM/state sidecar does not match. Create a new session for a changed ROM
or recipe. New geometry needs a new cold boot and checkpoint. State identity
headers are never rewritten, and a different emulator backend may be unable
to load the state.

## Reuse a cold boot already performed

```sh
python3 inspection.py adopt --session captures/fox-v1 --run /path/to/cold-boot-run --label my_spawn
```

Adoption requires a run that completed without core errors, started without a
state, used the session's ROM, declared the target stage in its recipe route,
and saved the named state. The native provenance sidecar must match the current
ROM and state and record a cold-boot origin. You still need to check the scene.
Only sessions without a primary checkpoint can adopt a run.

Keep paths in the same environment as the runner. Windows paths recorded in a
Windows session are not translated into Linux paths automatically; prepare and
adopt from WSL when running the WSL emulator.

## Camera and debug inspection

- `zoom`: two separate C-down taps, then a close-up capture.
- `orbit`: zoom, then four separate C-left taps with settling time and captures.
- `movement`: forward, left, forward, capturing after each input.

Camera controls depend on the game's camera mode. Holding a C button differs
from tapping it repeatedly. An `orbit_attempt` label records the input sent;
check the captures to see whether the camera rotated. The Engine Room Racing
Fox checkpoint tested during development uses camera mode 28, which
does not orbit with the ordinary C-left/right path. Scenery visibility and camera
obstruction are separate concerns.

An externally prepared experimental camera state can be registered explicitly:

```sh
python3 inspection.py register-debug --session captures/fox-v1 --state /path/to/camera-debug.st
python3 inspection.py run --session captures/fox-v1 --preset orbit --debug
```

The debug sidecar must have matching ROM/state hashes, an
`origin` of `derived_camera_debug_state`, the primary checkpoint's SHA1 as
`source_state_sha1`, and a nonempty edit manifest. These checks verify the
provenance fields; they cannot establish that the binary edits affect only the
camera. Debug replay requires `--debug`, is
labelled in run history, and works only with the orbit preset.
It cannot replace the primary checkpoint or serve as a normal movement check.

Experimental scenery-hidden ROMs are separate builds and therefore separate
sessions. Keep their patching outside the harness. Hiding world-cell drawing
does not necessarily hide objects or disable collision or camera obstruction.
Inspect final movement/contact in the normal visible level.

## Review the captures

Choose the actor and stage from existing metadata before running the emulator.
Use the generated shortest selector route rather than searching by screenshots.
Cold-boot once per build, inspect the stage/actor, then use small named presets.
Capture views that answer a specific question: rear and profile for silhouette,
movement views for attachments, visible-level contact for collision fit.

Capture success means images exist, contain nonblack pixels, and report no core
errors. It does not establish the stage, actor, geometry, shading, orbit or collision.
Check those through screenshots or RAM checks appropriate to the ROM and state.
Reusing a checkpoint does not validate a different ROM build.

## Checks

```sh
python3 -m unittest -v test_harness test_stage_routes test_inspection
```

Synthetic tests cover boot/replay selection, rejection of changed inputs,
adoption checks, missing provenance, debug replay, recording results, and
preserving the session after a harness failure. Keep observations from real
runs in the private session files.
