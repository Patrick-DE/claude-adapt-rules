#!/usr/bin/env bash
# Weekly deterministic pass for claude-learn (macOS/Linux twin of weekly_extract.ps1).
#
# Re-extracts ALL history, then archives every cited transcript. Full history, not a
# window: extract overwrites the corpus, so a windowed run would replace the complete
# corpus with a slice. Archiving matters because Claude Code deletes transcripts after
# cleanupPeriodDays (default 30) and rules outlive their evidence.
#
# Does NOT distil rules — that needs a model. Run /learn-rules afterwards.
#
# Install with cron, Mondays at 09:00:
#   0 9 * * 1 /path/to/claude-learn/hooks/weekly_extract.sh
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(dirname "$here")"
home_dir="${CLAUDE_LEARN_HOME:-$HOME/.claude-learn}"
log="$home_dir/data/reports/weekly.log"
mkdir -p "$(dirname "$log")"

stamp="$(date -u +%Y-%m-%dT%H:%M:%S)"

python_bin=""
for candidate in python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1; then
        python_bin="$candidate"
        break
    fi
done

if [ -z "$python_bin" ]; then
    echo "[$stamp] skipped: no python on PATH" >>"$log"
    exit 0
fi

export PYTHONPATH="$repo/src${PYTHONPATH:+:$PYTHONPATH}"

{
    echo "[$stamp] extract (full history)"
    "$python_bin" -m claude_learn.cli extract 2>&1 || true
    "$python_bin" -m claude_learn.cli archive 2>&1 || true
    echo "[$stamp] next step: run /learn-rules to distil the refreshed bundles"
} >>"$log"

exit 0
