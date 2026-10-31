# Stage routes

Generate a recipe to reach a stage from a cold boot:

```sh
python3 stage_routes.py --stage 3 5 7 --out-dir captures/stage-recipes
python3 stage_routes.py --all --out-dir captures/all-stage-recipes
./run_recipe.sh captures/stage-recipes/stage-05.json --rom /path/to/sssv.z64 --timeout 180
```

The generator follows the calibrated boot/menu sequence, enters the built-in
region unlock codes, then chooses the fewest Left/Right presses through the
unlocked stage selector. The selector starts at stage 1. `--all-unlocked` enters
all six unlock codes; otherwise it enables Europe and the target region. These
are controller cheats, not GameShark memory writes. Each run uses separate
harness settings and saves.

Stage IDs start at 1. Some examples:

| ID | Stage |
|---|---|
| 1 | Smashing Start |
| 3 | Honeymoon Lagoon |
| 5 | The Engine Room |
| 6 | Fat Bear Mountain |
| 7 | Rocky Hard Place |

Recipes capture the mission brief and initial spawn. Add `--diagnostic` for a
selector screenshot. Earlier calibration captures are replaced with neutral
waits of the same length to preserve the input schedule. Keep the intro waits:
shortening them previously sent inputs during cutscenes. The generator refuses
to overwrite existing output files.

## Check the destination

Generated recipes carry `source_derived_not_game_verified` metadata. Their
`ready: true` field allows execution; it does not confirm arrival at the target.
Check the mission brief for the stage and the spawn capture for the actor.

The generated stage-05 recipe was cold-booted and visually checked on 2026-10-29.
The brief named The Engine Room and the spawn showed the player Racing Fox.
That run confirmed the stage and actor only. It did not compare geometry or
validate other recipes. Other regions, selector wraparound, and special stages
still need in-game calibration.

Static animal placements or starting-species metadata can help choose a stage.
Coordinates alone do not establish a walkable route or an actor's live position.
For repeated checks of the same build, use an [inspection session](INSPECTION.md).
