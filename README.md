# SSSV Modkit Automated Testing

Repeat button presses and take screenshots in Space Station Silicon Valley.
Use this to check a mod, repeat a route through the game, or compare screenshots.

These are the emulator tools for [SSSV Modkit](https://github.com/sssv-modkit-dev/sssv-modkit).
They also work on their own and do not change your ROM.

## What do I need?

- Linux or WSL with a working graphics display, such as WSLg.
- Python 3.8+ and Bash. No extra Python packages are needed.
- Mupen64Plus and its Rice video, SDL input and HLE RSP plugins.
- Your own big-endian `.z64` ROM.

The current setup expects x86-64 Ubuntu library paths. See the
[setup details](docs/USAGE.md#setup) if yours are different.
ROMs, emulators, save states and game screenshots are not included.

## Take a screenshot

Run from the repository root:

```sh
./capture_rom.sh /path/to/your/sssv.z64 120f --dry-run
./capture_rom.sh /path/to/your/sssv.z64 120f
```

Replace the ROM path with your own. The first command checks the plan without
starting the emulator. The second runs for 120 rendered frames and takes a screenshot.
Results go in a new folder under `captures/`, with screenshots and logs.

## Repeat a test

A recipe is a JSON file listing waits, button presses and screenshots:

```sh
./run_recipe.sh recipes/known-scene.json --rom /path/to/your/sssv.z64 --timeout 30
```

On a US 1.0 ROM, this should capture yellow copyright text over a purple star
field at frames 120 and 180. Open the images to check your setup.

Other examples are in [`recipes/`](recipes/). The Fat Bear Mountain recipe
stops at the initial mouse spawn; it does not move the camera to a bear.

## Did the test pass?

Open the screenshots and read `summary.json` in the run folder.

| Result | Meaning |
| --- | --- |
| `capture_pass: true` | Images contain something other than black, and the emulator reported no errors |
| `semantic_pass: null` | No reference images were supplied, so image comparison was skipped |
| `semantic_pass: true` | The captures look similar to the reference images you supplied |

A screenshot can pass these checks and still show the wrong scene or a broken
mod. Inspect the result yourself. Use a fresh boot when checking a new ROM build;
a save state can still contain data from an older build.

## More help

- [Full usage, recipes, save states and image comparisons](docs/USAGE.md)
- [Routes to other stages](docs/STAGE-ROUTES.md)
- [Camera and movement checks from a save state](docs/INSPECTION.md)
- [Recorded capture checks and limits](docs/CAPTURE-VALIDATION.md)

## Development

These tests need no ROM or emulator:

```sh
python3 -m unittest -v test_harness test_stage_routes test_inspection test_semantic
bash -n capture_rom.sh run_recipe.sh
```

Most of the code is AI-written or generated using Claude and OpenAI coding tools.

## License

Original contributions use [CC0 1.0 Universal](LICENSE).
See [NOTICE.md](NOTICE.md) for game and third-party rights.
Contact: [sssv-modkit-dev@protonmail.me](mailto:sssv-modkit-dev@protonmail.me).

<p align="right"><sub>Made by FM</sub></p>
