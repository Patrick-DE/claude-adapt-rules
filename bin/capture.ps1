# SessionEnd hook shim for Windows without Git Bash.
# Prefer bin/capture.sh where bash exists; this is the PowerShell equivalent.
# Always exits 0 (see capture.py).

$ErrorActionPreference = 'SilentlyContinue'

try {
    $here = $PSScriptRoot
    $python = $null
    foreach ($candidate in @('python', 'python3', 'py')) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) { $python = $cmd.Source; break }
    }
    if (-not $python) { exit 0 }

    $raw = [Console]::In.ReadToEnd()
    $raw | & $python (Join-Path $here 'capture.py') 2>&1 | Out-Null
}
catch {
    # Deliberately swallowed: a capture hook must never fail a session.
}

exit 0
