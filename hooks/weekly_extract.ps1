# Weekly deterministic pass for claude-adapt-rules, run by Windows Task Scheduler.
#
# Re-extracts ALL history and refreshes the evidence bundles and report. Full
# history, not a --since window: extract overwrites the corpus, so a windowed run
# would silently replace the complete corpus with a two-week slice. Parsing every
# transcript takes seconds, so there is nothing to save by narrowing it.
#
# It does NOT distil rules: that needs a model. Run /claude-adapt-rules in Claude Code
# afterwards to turn the refreshed bundles into rule candidates.
#
# Exit code is always 0 — a scheduled job that reports failure every week gets
# ignored, and nothing here is urgent enough to warrant an alert.

$ErrorActionPreference = 'SilentlyContinue'

$repo = Split-Path -Parent $PSScriptRoot
$log = Join-Path $repo 'data\reports\weekly.log'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null

$stamp = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')

try {
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $python) { $python = (Get-Command py -ErrorAction SilentlyContinue).Source }
    if (-not $python) {
        Add-Content -Path $log -Value "[$stamp] skipped: no python on PATH"
        exit 0
    }

    $env:PYTHONPATH = Join-Path $repo 'src'
    $output = & $python -m claude_adapt_rules.cli extract 2>&1
    Add-Content -Path $log -Value "[$stamp] extract (full history)"
    Add-Content -Path $log -Value ($output | Out-String).TrimEnd()

    # Claude Code deletes transcripts after cleanupPeriodDays (default 30). Archive
    # every cited session right after extraction, or rules outlive their evidence.
    $archived = & $python -m claude_adapt_rules.cli archive 2>&1
    Add-Content -Path $log -Value ($archived | Out-String).TrimEnd()
    Add-Content -Path $log -Value "[$stamp] next step: run /claude-adapt-rules to distil the refreshed bundles"
}
catch {
    Add-Content -Path $log -Value "[$stamp] failed: $($_.Exception.Message)"
}

exit 0
