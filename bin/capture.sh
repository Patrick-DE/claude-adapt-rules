#!/usr/bin/env bash
# SessionEnd hook shim: find a Python interpreter and hand it the payload on stdin.
# Runs on macOS, Linux, and Windows via Git Bash. Always exits 0 (see capture.py).
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for candidate in python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1; then
        "$candidate" "$here/capture.py" >/dev/null 2>&1 || true
        exit 0
    fi
done

exit 0
