# Run the claude-adapt-rules CLI from anywhere without installing the package.
#   .\bin\claude-adapt-rules.ps1 extract
#   .\bin\claude-adapt-rules.ps1 pending -bundle C:\tmp\pending.md
param([Parameter(ValueFromRemainingArguments = $true)] $Args)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = if ($env:PYTHONPATH) {
    (Join-Path $root 'src') + [IO.Path]::PathSeparator + $env:PYTHONPATH
} else {
    Join-Path $root 'src'
}

$python = $null
foreach ($candidate in @('python', 'python3', 'py')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) { $python = $cmd.Source; break }
}
if (-not $python) {
    Write-Error 'claude-adapt-rules: no python interpreter found on PATH'
    exit 127
}

& $python -m claude_adapt_rules.cli @Args
exit $LASTEXITCODE
