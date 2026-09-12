$ErrorActionPreference = "Stop"

$suldeRoot = if ($env:SULDE_HOME) {
    $env:SULDE_HOME
} else {
    Join-Path $HOME ".sulde"
}
$launcher = Join-Path $suldeRoot "bin/sulde-kb-mcp"
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    [Console]::Error.WriteLine("sulde-kb-mcp: stable launcher unavailable: $launcher")
    exit 2
}

$pythonCandidates = @(
    (Join-Path $suldeRoot "venv/Scripts/python.exe"),
    "python3.exe",
    "python.exe",
    "py.exe"
)
$python = $null
foreach ($candidate in $pythonCandidates) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $python = (Resolve-Path -LiteralPath $candidate).Path
        break
    }
    $command = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($command) {
        $python = $command.Source
        break
    }
}
if (-not $python) {
    [Console]::Error.WriteLine("sulde-kb-mcp: Python interpreter unavailable")
    exit 2
}

$env:PYTHONDONTWRITEBYTECODE = "1"
& $python $launcher @args
exit $LASTEXITCODE
