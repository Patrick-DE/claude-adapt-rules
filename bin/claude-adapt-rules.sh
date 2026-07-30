#!/usr/bin/env bash
# Run the claude-adapt-rules CLI from anywhere without installing the package.
#   bin/claude-adapt-rules.sh extract
#   bin/claude-adapt-rules.sh pending --bundle /tmp/pending.md
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$here/../src${PYTHONPATH:+:$PYTHONPATH}"

for candidate in python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1; then
        exec "$candidate" -m claude_adapt_rules.cli "$@"
    fi
done

echo "claude-adapt-rules: no python interpreter found on PATH" >&2
exit 127
