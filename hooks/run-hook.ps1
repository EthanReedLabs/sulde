param([Parameter(Position = 0)][string]$Hook)
$scripts = @{
    "pre-tool-use" = "pre_tool_use.py"
    "user-prompt-submit" = "user_prompt_submit.py"
    "session-start" = "session_start.py"
    "pre_tool_use.py" = "pre_tool_use.py"
    "post_tool_use.py" = "post_tool_use.py"
    "user_prompt_submit.py" = "user_prompt_submit.py"
    "canon_inject.py" = "canon_inject.py"
    "session_start.py" = "session_start.py"
    "pre_compact.py" = "pre_compact.py"
    "notification.py" = "notification.py"
    "stop.py" = "stop.py"
}
if (-not $scripts.ContainsKey($Hook) -or $args.Count -ne 0) {
    Write-Error "sulde: exactly one known Hook entrypoint is required"
    exit 2
}
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$kbRoot = $env:SULDE_KB_HOME
if (-not $kbRoot) {
    $suldeRoot = $env:SULDE_HOME
    if (-not $suldeRoot) { $suldeRoot = Join-Path ([Environment]::GetFolderPath("UserProfile")) ".sulde" }
    $kbRoot = Join-Path $suldeRoot "data/kb"
}
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"
$candidates = @(
    [pscustomobject]@{ Name = (Join-Path $kbRoot "venv/Scripts/python.exe"); Prefix = @() },
    [pscustomobject]@{ Name = (Join-Path $kbRoot "venv/bin/python"); Prefix = @() },
    [pscustomobject]@{ Name = "python3"; Prefix = @() },
    [pscustomobject]@{ Name = "python"; Prefix = @() },
    [pscustomobject]@{ Name = "py"; Prefix = @("-3") }
)
foreach ($candidate in $candidates) {
    $command = Get-Command $candidate.Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $command) { continue }
    & $command.Source @($candidate.Prefix) -B -c 'import sys, yaml; raise SystemExit(0 if sys.version_info >= (3, 10) and sys.version_info[:2] <= (3, 14) and int(yaml.__version__.split(".")[0]) >= 6 else 1)' *> $null
    if ($LASTEXITCODE -eq 0) {
        & $command.Source @($candidate.Prefix) -B (Join-Path $scriptDir $scripts[$Hook])
        exit $LASTEXITCODE
    }
}
Write-Error "sulde: Python 3.10–3.14 with PyYAML 6+ is required; Hook did not execute"
exit 2
