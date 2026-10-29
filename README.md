# SSSV Modkit Automated Testing

Capture screenshots and run frame-based button recipes for Space Station Silicon Valley
using Mupen64Plus on Linux/WSL. This is a separate emulator harness from
[sssv-modkit](https://github.com/sssv-modkit-dev/sssv-modkit). It never writes ROM bytes
and does not require the mod builder or its generated indexes.

## Requirements

- Python 3.8+ and Bash; no Python packages required.
- Your own big-endian `.z64` ROM.
- A compatible Mupen64Plus installation and working graphics display, such as WSLg.
  The current backend targets x86-64 Ubuntu: `libmupen64plus.so.2`, Rice video,
  SDL input, HLE RSP, and core data under `/usr/share/games/mupen64plus`.
  Plugin libraries are loaded from `/usr/lib/x86_64-linux-gnu/mupen64plus`.
  The development installation uses core/plugin packages from the 2.5.9 series.
  Audio is not attached. Other platforms or backend layouts need adaptation.

Install emulator components separately; this repository does not bundle them.
Synthetic tests and dry-runs do not load emulator libraries.

## Quick start

Run from the repository root. Set a local ROM path or pass one explicitly:

```sh
export SSSV_ROM=/path/to/your/sssv.z64
./capture_rom.sh 120f --dry-run
./capture_rom.sh 120f
./run_recipe.sh recipes/fat-bear-mountain.json --dry-run
./run_recipe.sh recipes/fat-bear-mountain.json --timeout 180
```

Explicit paths work without the environment variable:

```sh
./capture_rom.sh /path/to/your/sssv.z64 120f
./run_recipe.sh recipes/input-smoke.json --rom /path/to/your/sssv.z64
```

Outputs go to unique `captures/DATE/TIME-ID/` directories. Set `SSSV_TEST_DIR`
to another parent directory to keep evidence elsewhere. Each run has its own
emulator configuration and game-save directory. Each run uses fresh defaults,
640x480 windowed video, no vertical sync, and no Game Boy camera device.
Personal saves and settings are not read or overwritten.

## Repeatable known-scene capture

From Linux/WSL, run with your own US 1.0 ROM:

```sh
./run_recipe.sh recipes/known-scene.json --rom /path/to/sssv.z64 --timeout 30
```

This cold-boots without input and captures rendered frames 120 and 180. Both
images should show yellow copyright text over a purple star field. The second
checkpoint is dimmer as the scene fades. Inspect both images when calibrating a
new ROM/backend. Repeat the command to compare each checkpoint's `rgb_sha1` in
`summary.json`; compare the same frame across runs, not frame 120 against 180.
Hashes are evidence of repeatability on the same setup, not portable scene
recognition. `semantic_pass` remains null.

The stock US 1.0 ROM was verified with three independent cold boots on the
development Rice/Mesa backend: both checkpoints were nonblack and byte-identical
across runs, with no core errors. The first rendered frame is still black during
boot. Capturing at `1f` intentionally fails the capture check; waiting for a
known checkpoint avoids that startup blank. Frames are never silently retried
or moved to a later scene. See [capture validation](docs/CAPTURE-VALIDATION.md).

## Recipes and frame counts

| Recipe | Purpose |
|---|---|
| `recipes/known-scene.json` | Quick cold-boot copyright scene at frames 120 and 180 |
| `recipes/boot-calibration.json` | Observe cold boot and Start responses |
| `recipes/fat-bear-mountain.json` | Cold boot to that stage's initial mouse spawn |
| `recipes/input-smoke.json` | Short button press/release capture |
| `recipes/state-smoke.json` | Exercise a native-state save request |

The stage route has been exercised during development on a local patched ROM.
Timing can vary by ROM and backend; inspect the final scene. It stops at the
mouse spawn and does not navigate the camera to a bear. The state smoke recipe
does not prove arbitrary boot/cutscene states will reload successfully.

`f` counts rendered frames. Historical `s`, `m`, and `h` durations convert at
30 frames per second; they do not measure elapsed wall-clock time.
Presses have both hold and neutral release intervals. `UP/DOWN/LEFT/RIGHT`
drive the analog stick; `DPAD_*` drives the D-pad. Other buttons are START,
A, B, Z, L, R, and C_UP/C_DOWN/C_LEFT/C_RIGHT.

```json
{"version":1,"ready":true,"steps":[
  {"action":"wait","frames":60},
  {"action":"press","buttons":["START"],"frames":3,"release_frames":30},
  {"action":"capture","label":"menu"}
]}
```

Recipes permit wait, press, capture, and save_state actions. They cannot execute
shell commands, reset, or load states mid-run. `ready: true` enables execution;
it does not assert the captured scene is correct. Use `--dry-run` to review the
schedule without starting the core or creating a capture directory.

## Evidence and save states

Runs contain a plan with ROM/state hashes, an emulator log, PNGs, and result/summary
JSON. A completed run reports `semantic_pass: null`: inspect the screenshots or
perform a separate RAM check to establish the intended scene and geometry.
`capture_pass: true` means PNGs were produced with nonblack pixels and no core
errors; it does not establish scene correctness. Core errors, missing captures,
or any all-black capture produce `status: capture_invalid`, `capture_pass: false`,
`review_required: true`, and exit code 1. Evidence is retained. Timeouts and
execution errors produce `status: failed`. Captures include raw RGB and PNG SHA1
hashes. Dark or incorrect scenes can still require visual review.

Use `--state /path/to/matching.st` with capture or recipe commands when needed.
Recipes marked `cold_boot_only` reject it. Native states have a `.st.json`
provenance sidecar that checks both ROM and state SHA1. Recognized Project64
ZIP states have their recorded ROM CRC identity checked; the core still validates
loading. External-state compatibility is limited. Matching hashes do not prove
loaded RAM contains patched geometry: use a cold boot to validate a new build.
Do not rewrite state headers to bypass identity checks.

Captures, logs, states, local inputs, and emulator settings stay private.

## Development and license

```sh
python3 -m unittest -v test_harness
bash -n capture_rom.sh run_recipe.sh
```

Tests use synthetic inputs and need no ROM or emulator installation. Development
uses assistance from Claude and OpenAI coding tools, with owner review and testing.
Original contributions are dedicated under [CC0 1.0 Universal](LICENSE).
See [NOTICE.md](NOTICE.md). Contact:
[sssv-modkit-dev@protonmail.me](mailto:sssv-modkit-dev@protonmail.me).

<p align="right"><sub>Made by FM</sub></p>
