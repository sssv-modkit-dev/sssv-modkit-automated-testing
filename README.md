# SSSV Modkit Automated Testing

Run button sequences and capture screenshots from **Space Station Silicon Valley**
with Mupen64Plus on Linux or WSL. Use it to repeat a test scene, compare captures,
or save a checkpoint for inspecting a ROM build.

This is the emulator harness for [SSSV Modkit](https://github.com/sssv-modkit-dev/sssv-modkit).
It also runs on its own: it needs no mod builder or animal table and does not edit ROMs.
No ROMs, emulator binaries, save states, or game captures are included.

## Setup

You need Python 3.8+, Bash, your own legally obtained big-endian `.z64` ROM,
and Mupen64Plus with a working graphics display, such as WSLg. No Python packages
are required.

The backend currently expects x86-64 Ubuntu with these components:

- `libmupen64plus.so.2`, Rice video, SDL input, and HLE RSP
- Plugin libraries in `/usr/lib/x86_64-linux-gnu/mupen64plus`
- Core data in `/usr/share/games/mupen64plus`

Development uses the 2.5.9 core/plugin packages. Install them separately. Audio
is not attached, and other platforms or library layouts need changes to the backend.
Tests and dry runs work without emulator libraries.

## First capture

Run from the repository root:

```sh
export SSSV_ROM=/path/to/your/sssv.z64
./capture_rom.sh 120f --dry-run
./capture_rom.sh 120f
```

Or pass the ROM path directly:

```sh
./capture_rom.sh /path/to/your/sssv.z64 120f
```

Each run writes to a new `captures/DATE/TIME-ID/` directory. Set `SSSV_TEST_DIR`
to use a different parent directory. Runs use separate settings and saves, with
640x480 windowed video, no vertical sync, and no Game Boy camera device. Your
personal settings and saves are left alone.

For a first check on a US 1.0 ROM, capture the copyright scene:

```sh
./run_recipe.sh recipes/known-scene.json --rom /path/to/sssv.z64 --timeout 30
```

Frames 120 and 180 should show yellow copyright text over a purple star field;
frame 180 is dimmer as the scene fades. Inspect both images on a new setup.
To check repeatability, run the command again and compare each frame's `rgb_sha1`
in `summary.json` with the same frame from the previous run.

These checkpoints matched across three cold boots on the development Rice/Mesa
backend. Hashes may differ on other setups. Frame 1 is black during startup and
intentionally fails the capture check. See [capture validation](docs/CAPTURE-VALIDATION.md)
for the recorded results and limits.

## Run a recipe

Recipes schedule button presses, waits, screenshots, and save-state requests:

```sh
./run_recipe.sh recipes/fat-bear-mountain.json --dry-run
./run_recipe.sh recipes/fat-bear-mountain.json --timeout 180
./run_recipe.sh recipes/input-smoke.json --rom /path/to/your/sssv.z64
```

| Recipe | What it does |
|---|---|
| `recipes/known-scene.json` | Captures the copyright scene at frames 120 and 180 |
| `recipes/boot-calibration.json` | Captures cold boot and Start responses |
| `recipes/fat-bear-mountain.json` | Routes from cold boot to the initial mouse spawn |
| `recipes/input-smoke.json` | Presses and releases a button, then captures |
| `recipes/state-smoke.json` | Requests a native save state |

Timing can vary by ROM and backend, so inspect the final scene. The Fat Bear
Mountain route stops at the mouse spawn; it does not move the camera to a bear.
The state smoke test does not establish whether other boot or cutscene states reload.

`f` counts rendered frames. The older `s`, `m`, and `h` duration suffixes convert
at 30 frames per second, regardless of elapsed time. Presses include a hold and
a neutral release interval. `UP/DOWN/LEFT/RIGHT` control the analog stick;
`DPAD_*` controls the D-pad. Other buttons are START, A, B, Z, L, R, and
C_UP/C_DOWN/C_LEFT/C_RIGHT.

```json
{"version":1,"ready":true,"steps":[
  {"action":"wait","frames":60},
  {"action":"press","buttons":["START"],"frames":3,"release_frames":30},
  {"action":"capture","label":"menu"}
]}
```

The supported actions are `wait`, `press`, `capture`, and `save_state`. Recipes
cannot run shell commands, reset the core, or load states mid-run. `ready: true`
allows execution; it does not confirm the scene. Use `--dry-run` to inspect the
schedule without starting the emulator or creating a capture directory.

For other stages, see [stage routes](docs/STAGE-ROUTES.md). For repeated camera
and movement checks from a saved checkpoint, see [inspection sessions](docs/INSPECTION.md).

## Read the results

A run saves its plan, ROM/state hashes, emulator log, PNGs, and result/summary JSON.
Captures include raw RGB and PNG SHA1 hashes.

| Result | Meaning |
|---|---|
| `capture_pass: true` | PNGs contain nonblack pixels and the core reported no errors |
| `status: capture_invalid` | A capture is missing or all black, or the core reported an error; exit code 1 |
| `status: failed` | Execution failed or timed out |
| `semantic_pass: null` | The harness has not checked the scene or geometry |

Invalid captures also set `capture_pass: false` and `review_required: true`.
The run's files are kept for inspection. A capture pass can still show the wrong
scene, rendering problems, or a mostly dark image. Check screenshots or use a
separate RAM check for the scene and geometry you intended to test.

## Save states

Pass `--state /path/to/matching.st` to a capture or recipe command to start from
a state. Recipes marked `cold_boot_only` reject this option.

Native states use a `.st.json` sidecar to check the ROM and state SHA1 hashes.
For recognized Project64 ZIP states, the harness checks the recorded ROM CRC
identity; the core still checks loading. Compatibility with external states is limited.

A matching hash does not prove that loaded RAM contains a new build's patched
geometry. Cold-boot each new build before validating it. Do not rewrite state
headers to bypass identity checks. Keep captures, logs, states, local inputs,
and emulator settings private.

## Development

```sh
python3 -m unittest -v test_harness test_stage_routes test_inspection
bash -n capture_rom.sh run_recipe.sh
```

Tests use synthetic inputs and need no ROM or emulator installation.
Development uses Claude and OpenAI coding tools, with owner review and testing.

Original contributions are dedicated under [CC0 1.0 Universal](LICENSE).
See [NOTICE.md](NOTICE.md) for game and third-party rights.
Contact: [sssv-modkit-dev@protonmail.me](mailto:sssv-modkit-dev@protonmail.me).

<p align="right"><sub>Made by FM</sub></p>
