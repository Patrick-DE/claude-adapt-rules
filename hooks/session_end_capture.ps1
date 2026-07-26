# SessionEnd capture for claude-learn.
#
# Reads the hook payload from stdin, extracts transcript_path, and appends this
# session's correction candidates to data/queue/queue.jsonl.
#
# Contract: ALWAYS exit 0 and never write to stderr. A capture step that can fail
# is a capture step that breaks unrelated work in every project. Failures are
# recorded in data/hook.log by the CLI instead.

$ErrorActionPreference = 'SilentlyContinue'

try {
    $raw = [Console]::In.ReadToEnd()
    if (-not $raw) { exit 0 }

    $payload = $raw | ConvertFrom-Json
    $transcript = $payload.transcript_path
    if (-not $transcript) { exit 0 }
    if (-not (Test-Path -LiteralPath $transcript)) { exit 0 }

    $repo = Split-Path -Parent $PSScriptRoot
    $env:PYTHONPATH = Join-Path $repo 'src'

    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $python) { $python = (Get-Command py -ErrorAction SilentlyContinue).Source }
    if (-not $python) { exit 0 }   # no interpreter: stay silent, break nothing

    & $python -m claude_learn.cli queue --transcript $transcript --quiet 2>&1 | Out-Null
}
catch {
    # Deliberately swallowed: see contract above.
}

exit 0
