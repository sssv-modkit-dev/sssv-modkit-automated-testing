#!/usr/bin/env bash
set -eu
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec python3 "$HERE/harness.py" recipe "$@"
