param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$candidates = @(
    [pscustomobject]@{ Name = "python3"; Prefix = @() },
    [pscustomobject]@{ Name = "python"; Prefix = @() },
    [pscustomobject]@{ Name = "py"; Prefix = @("-3") }
)

foreach ($candidate in $candidates) {
    $command = Get-Command $candidate.Name -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $command) { continue }
    & $command.Source @($candidate.Prefix) -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
    if ($LASTEXITCODE -eq 0) {
        & $command.Source @($candidate.Prefix) (Join-Path $scriptDir "sulde.py") @Arguments
        exit $LASTEXITCODE
    }
}

Write-Error "sulde: Python 3.10+ is required"
exit 2
