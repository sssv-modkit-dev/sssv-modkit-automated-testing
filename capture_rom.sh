#!/usr/bin/env bash
# CLI compatibility wrapper; implementation and per-run evidence live in harness.py.
set -eu
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec python3 "$HERE/harness.py" capture "$@"
