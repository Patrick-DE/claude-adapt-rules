#!/usr/bin/env bash
# Weekly deterministic pass for claude-adapt-rules (macOS/Linux twin of weekly_extract.ps1).
#
# Re-extracts ALL history, then archives every cited transcript. Full history, not a
# window: extract overwrites the corpus, so a windowed run would replace the complete
# corpus with a slice. Archiving matters because Claude Code deletes transcripts after
# cleanupPeriodDays (default 30) and rules outlive their evidence.
#
# Does NOT distil rules — that needs a model. Run /claude-adapt-rules afterwards.
#
# Install with cron, Mondays at 09:00:
#   0 9 * * 1 /path/to/claude-adapt-rules/hooks/weekly_extract.sh
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(dirname "$here")"
home_dir="${CLAUDE_ADAPT_RULES_HOME:-$HOME/.claude-adapt-rules}"
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
    "$python_bin" -m claude_adapt_rules.cli extract 2>&1 || true
    "$python_bin" -m claude_adapt_rules.cli archive 2>&1 || true
} >>"$log"

# Unattended distillation. Opt-in, because it is the only step that needs a model
# and therefore the only one that can cost money or hang. Set
# CLAUDE_ADAPT_RULES_DISTIL=1 to enable.
#
# It drafts candidates and stops. Ingest stays manual on purpose: a bad rule
# reaches every session of every project, and global text waits for a human yes.
if [ "${CLAUDE_ADAPT_RULES_DISTIL:-0}" = "1" ]; then
    day="$(date -u +%Y-%m-%d)"
    bundle="$home_dir/data/corpus/pending.md"
    draft="$home_dir/rules/candidates/$day.draft.json"
    final="$home_dir/rules/candidates/$day.json"
    mkdir -p "$(dirname "$draft")"

    {
        if ! command -v claude >/dev/null 2>&1; then
            echo "[$stamp] distil skipped: no claude CLI on PATH"
        else
            "$python_bin" -m claude_adapt_rules.cli pending --bundle "$bundle" 2>&1 || true
            claude -p "Read $bundle and the skill claude-adapt-rules. Write rule
candidates as JSON to $draft. Quote verbatim from the User said blocks only." \
                >/dev/null 2>&1 || echo "[$stamp] distil: model call failed"

            # The gate that replaces the human reader: keep only candidates whose
            # every quote is verbatim in the session it cites.
            if [ -f "$draft" ]; then
                "$python_bin" -m claude_adapt_rules.cli check-candidates "$draft" \
                    --write-accepted "$final" 2>&1 || true
                echo "[$stamp] distil: drafted -> $final (review, then ingest)"
            else
                echo "[$stamp] distil: no draft produced"
            fi
        fi
    } >>"$log"
fi

echo "[$stamp] next step: review candidates, then ingest" >>"$log"

exit 0
