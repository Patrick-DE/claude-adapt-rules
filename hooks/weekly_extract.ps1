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

    # Unattended distillation. Opt-in, because it is the only step that needs a
    # model and therefore the only one that can cost money or hang. Set
    # CLAUDE_ADAPT_RULES_DISTIL=1 to enable.
    #
    # It drafts candidates and stops. Ingest stays manual on purpose: a bad rule
    # reaches every session of every project, and global text waits for a human yes.
    if ($env:CLAUDE_ADAPT_RULES_DISTIL -eq '1') {
        $homeDir = if ($env:CLAUDE_ADAPT_RULES_HOME) { $env:CLAUDE_ADAPT_RULES_HOME } else { Join-Path $env:USERPROFILE '.claude-adapt-rules' }
        $day = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd')
        $bundle = Join-Path $homeDir 'data\corpus\pending.md'
        $draft = Join-Path $homeDir "rules\candidates\$day.draft.json"
        $final = Join-Path $homeDir "rules\candidates\$day.json"
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $draft) | Out-Null

        $claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
        if (-not $claude) {
            Add-Content -Path $log -Value "[$stamp] distil skipped: no claude CLI on PATH"
        }
        else {
            & $python -m claude_adapt_rules.cli pending --bundle $bundle 2>&1 | Out-Null
            $prompt = "Read $bundle and the skill claude-adapt-rules. Write rule candidates as JSON to $draft. Quote verbatim from the User said blocks only."
            & $claude -p $prompt 2>&1 | Out-Null

            # The gate that replaces the human reader: keep only candidates whose
            # every quote is verbatim in the session it cites.
            if (Test-Path $draft) {
                $checked = & $python -m claude_adapt_rules.cli check-candidates $draft --write-accepted $final 2>&1
                Add-Content -Path $log -Value ($checked | Out-String).TrimEnd()
                Add-Content -Path $log -Value "[$stamp] distil: drafted -> $final (review, then ingest)"
            }
            else {
                Add-Content -Path $log -Value "[$stamp] distil: no draft produced"
            }
        }
    }

    Add-Content -Path $log -Value "[$stamp] next step: review candidates, then ingest"
}
catch {
    Add-Content -Path $log -Value "[$stamp] failed: $($_.Exception.Message)"
}

exit 0
