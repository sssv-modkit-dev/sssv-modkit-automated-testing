# Capture validation

Verified 2026-10-29 using the stock US 1.0 ROM (SHA1
`e5e09205aa743a9e5043a42df72adc379c746b0b`) on x86-64 Ubuntu/WSL,
Mupen64Plus core/Rice/SDL input/HLE RSP, and Mesa llvmpipe OpenGL.
No game inputs or screenshots are distributed with this report.

## Findings

- A cold-boot capture at rendered frame 1 is all black. At frames 60 and 120,
  the original harness read visible copyright text. The blank image occurs
  during early boot. These results gave no reason to change the framebuffer API
  or retry a requested capture at a different frame.
- `Failed to open video device 0` came from the unused Game Boy camera input,
  not the Rice screenshot readback. Setting `GbCameraVideoCaptureBackend1` to
  `dummy` removes that error without suppressing error reporting.
- Personal settings were previously copied into each run. Fresh settings
  and fixed video dimensions remove that source of variation. Personal
  settings and saves are preserved.
- Black captures previously completed with exit code 0 and a review flag. They
  now return `capture_invalid` and exit 1. A nonblack image still needs review
  to check the scene.

The [core front-end API](https://mupen64plus.org/wiki/index.php/Mupen64Plus_v2.0_Core_Front-End)
permits `ReadScreen2` in the frame callback. The
[camera backend implementation](https://github.com/mupen64plus/mupen64plus-core/blob/master/src/backends/api/video_capture_backend.c)
provides a dummy input backend separate from video readback.

## Known scene

Run `recipes/known-scene.json` as shown in the README. Images were visually
checked: yellow copyright text over the purple star field at both frames,
fading at frame 180. Three independent cold boots returned `capture_pass: true`,
`review_required: false`, no core errors, and these matching checkpoint hashes:

| Rendered frame | Raw RGB SHA1 | PNG SHA1 |
|---|---|---|
| 120 | `f0b038892e5197ada60ad9e30ef957f319468411` | `d598128017781fe5e8b4f9ef7a6a06131cf82874` |
| 180 | `f023f2b69789804c7299c355c02b680e445fb713` | `515243e3ab3e75d8acdc8a2ecc54fac59a733cc7` |

These hashes were recorded on this backend; other renderers may differ.
`semantic_pass` remains null. This scene checks capture reliability; it does not validate gameplay, state compatibility, or patched
geometry. Plans, logs, isolated settings, PNGs, and results remain in the
git-ignored `captures/` tree.

## Longer route check

The existing `fat-bear-mountain.json` route was also run with the stock ROM and
isolated defaults. All 23 captures were nonblack; the mission brief identified
Fat Bear Mountain and the final image showed the initial mouse spawn. A native
state and matching provenance sidecar were saved. The route was run once, so
repeatability was not checked. Rice printed a shader compilation diagnostic
during the route outside the core error callback; visual artifacts remain possible even
when `capture_pass` is true. State replay and patched geometry were not validated.
