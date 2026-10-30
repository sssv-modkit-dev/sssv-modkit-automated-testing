# Reusable inspection workflow

An inspection session binds one exact ROM build to a target stage, generated
recipes, a cold-boot checkpoint, optional debug checkpoint, and run history.
It uses existing harness recipes and state provenance; it does not patch ROMs,
change native states, or require the modkit or an animal table.

## Prepare once, then replay

Run on the Linux/WSL backend supported by the harness. Keep the session under
`captures/` so local paths, hashes, states and evidence remain ignored.

```sh
python3 inspection.py prepare --session captures/fox-v1 --stage 5 --rom /path/to/build.z64
python3 inspection.py run --session captures/fox-v1
# Inspect mission_brief.png and spawn.png in the reported run directory.
python3 inspection.py review --session captures/fox-v1 --note 'Describe what you actually observed.'
python3 inspection.py run --session captures/fox-v1 --preset zoom
python3 inspection.py run --session captures/fox-v1 --preset movement
```

The first `run` executes only the cold-boot bootstrap, saves `inspection_spawn.st`,
and registers it only after a successful run with matching provenance. The next
`run` uses that checkpoint and the requested preset. `--dry-run` shows the command
without launching an emulator; `--timeout` sets the harness timeout in seconds.
Run one inspection at a time; input/display access and session updates are not
coordinated across concurrent emulator processes.

The session directory contains `session.json`, four generated recipe JSON files,
and per-run captures, plans, logs, result/summary JSON and state sidecars. History
records the source cold boot and elapsed replay times. A manual review note is
stored separately and never changes `semantic_pass` into an automated pass.

The ROM SHA1 and recipe contents are pinned. Replacing a ROM or changing a recipe
causes a refusal: create a new session. The registered checkpoint SHA1 is pinned
in addition to checking its ROM/state sidecar. A missing, modified or mismatched
registered checkpoint causes a refusal rather than a silent fresh boot. Nothing
rewrites state identity headers. New geometry needs a new cold boot and checkpoint.
Changing emulator backends can also invalidate native-state compatibility.

## Reuse a cold boot already performed

```sh
python3 inspection.py adopt --session captures/fox-v1 --run /path/to/cold-boot-run --label my_spawn
```

Adoption checks that the run completed without core errors, started without a
state, used this exact ROM, declares this target stage in its recipe route, and
saved the named state. The native provenance sidecar must match the current ROM
and state and record a cold-boot origin. Adoption does not infer scene correctness
from a nonblack screenshot. Only sessions without a primary checkpoint can adopt.

Keep paths in the same environment as the runner. Windows paths recorded in a
Windows session are not translated into Linux paths automatically; prepare and
adopt from WSL when running the WSL emulator.

## Camera and debug inspection

- `zoom`: two separate C-down taps, then a close-up capture.
- `orbit`: zoom, then four separate C-left taps with settling time and captures.
- `movement`: forward, left, forward, capturing after each input.

Camera controls are mode-limited. Holding C buttons is not equivalent to repeated
taps; an `orbit_attempt` label records input, not a verified rotation. The Engine
Room Racing Fox checkpoint tested during development uses camera mode 28, which
does not orbit with the ordinary C-left/right path. Scenery visibility and camera
obstruction are separate concerns.

An externally prepared experimental camera state can be registered explicitly:

```sh
python3 inspection.py register-debug --session captures/fox-v1 --state /path/to/camera-debug.st
python3 inspection.py run --session captures/fox-v1 --preset orbit --debug
```

The debug sidecar must have matching ROM/state hashes, an
`origin` of `derived_camera_debug_state`, the primary checkpoint's SHA1 as
`source_state_sha1`, and a nonempty edit manifest. These checks verify declared
provenance, not that arbitrary binary edits are limited to a camera. Debug replay
is labelled in run history, is opt-in, and is restricted to the orbit preset.
It cannot replace the primary checkpoint or serve as a normal movement check.

Experimental scenery-hidden ROMs are separate builds and therefore separate
sessions. Keep their patching outside the harness. Hiding world-cell drawing
does not necessarily hide objects or disable collision or camera obstruction.
Inspect final movement/contact in the normal visible level.

## What to automate and what to inspect

Choose the actor and stage from existing metadata before running the emulator.
Use the generated shortest selector route rather than searching by screenshots.
Cold-boot once per build, inspect the stage/actor, then use small named presets.
Capture views that answer a specific question: rear and profile for silhouette,
movement views for attachments, visible-level contact for collision fit.

Capture success means images exist, contain nonblack pixels, and report no core
errors. It does not establish the stage, actor, geometry, shading, orbit or collision.
Use screenshots or independently scoped RAM checks for those claims. A fast
checkpoint is an iteration tool, not evidence that a different ROM loaded correctly.

## Checks

```sh
python3 -m unittest -v test_harness test_stage_routes test_inspection
```

Synthetic session tests cover cold-boot/replay selection, changed ROM/recipe/state
refusal, failed or mismatched run adoption, missing provenance, separate opt-in
debug replay, evidence recording, and preservation of the session on harness failure.
Actual run observations belong in the private session evidence, not test fixtures.
