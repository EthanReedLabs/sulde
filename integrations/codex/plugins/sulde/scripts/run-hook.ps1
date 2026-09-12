param(
    [Parameter(Position = 0)]
    [string]$Hook
)

$env:PYTHONDONTWRITEBYTECODE = "1"

if ($Hook -notin @("session-start", "user-prompt-submit", "pre-tool-use", "permission-request", "post-tool-use", "stop")) {
    Write-Error "usage: run-hook.ps1 {session-start|user-prompt-submit|pre-tool-use|permission-request|post-tool-use|stop}"
    exit 2
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptName = switch ($Hook) {
    "session-start" { "session-start.py" }
    "user-prompt-submit" { "user-prompt-submit.py" }
    "pre-tool-use" { "pre-tool-use.py" }
    "permission-request" {
        $env:SULDE_CODEX_HOOK_EVENT = "PermissionRequest"
        "pre-tool-use.py"
    }
    "post-tool-use" { "post-tool-use.py" }
    "stop" { "stop.py" }
}
$hookPayload = [Console]::In.ReadToEnd()

$candidates = @(
    [pscustomobject]@{ Name = "python3"; Args = @() },
    [pscustomobject]@{ Name = "python"; Args = @() },
    [pscustomobject]@{ Name = "py"; Args = @("-3") }
)
$pythonPath = $null
$pythonArgs = @()
foreach ($candidate in $candidates) {
    $command = Get-Command $candidate.Name -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $command) { continue }
    $probeArgs = @($candidate.Args)
    & $command.Source @probeArgs -c "import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)" *> $null
    if ($LASTEXITCODE -eq 0) {
        $pythonPath = $command.Source
        $pythonArgs = $probeArgs
        break
    }
}

$script:nonblockingFailureRecorded = $false
function Invoke-ObservedHook {
    param([string]$Stage, [string[]]$CommandArgs)
    $observer = Join-Path $scriptDir "_hook_observer.py"
    if (Test-Path -LiteralPath $observer -PathType Leaf) {
        $hookPayload | & $pythonPath @pythonArgs $observer --hook "sulde:$Hook" --stage $Stage -- @CommandArgs
    } else {
        [Console]::Error.WriteLine("sulde: hook_observer_unavailable; coverage_blind_spot")
        $executable = $CommandArgs[0]
        $remaining = @($CommandArgs | Select-Object -Skip 1)
        $hookPayload | & $executable @remaining
    }
}
function Write-NonblockingHookFailure {
    param(
        [string]$Stage = "wrapper",
        [string]$ErrorKind = "nonzero_exit",
        [int]$ExitCode = 1
    )
    if ($Hook -eq "pre-tool-use" -or $script:nonblockingFailureRecorded -or -not $pythonPath) {
        return
    }
    $script:nonblockingFailureRecorded = $true
    $recorder = Join-Path $scriptDir "record-hook-failure.py"
    if (Test-Path -LiteralPath $recorder -PathType Leaf) {
        & $pythonPath @pythonArgs $recorder $Hook $Stage $ErrorKind $ExitCode > $null
    }
}

trap {
    if ($Hook -ne "pre-tool-use") {
        Write-NonblockingHookFailure -Stage "wrapper" -ErrorKind "unexpected_error" -ExitCode 1
        exit 0
    }
    break
}

function Test-ValidPolicyDeny {
    param(
        [string]$EventName,
        [string]$Payload
    )
    if ($EventName -ne "pre-tool-use" -or [string]::IsNullOrWhiteSpace($Payload)) {
        return $false
    }
    try {
        $decoded = $Payload | ConvertFrom-Json -ErrorAction Stop
        $output = $decoded.hookSpecificOutput
        return (
            $null -ne $output -and
            $output.hookEventName -eq "PreToolUse" -and
            $output.permissionDecision -eq "deny" -and
            $output.permissionDecisionReason -is [string] -and
            -not [string]::IsNullOrWhiteSpace($output.permissionDecisionReason)
        )
    } catch {
        return $false
    }
}

function Invoke-PreToolFallback {
    if (-not $pythonPath) {
        [Console]::Out.WriteLine('{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Sulde PreToolUse cannot start without Python 3; this action was not executed."}}')
        return
    }
    $previousFallback = $env:SULDE_CODEX_FALLBACK_ONLY
    $env:SULDE_CODEX_FALLBACK_ONLY = "1"
    try {
        $fallbackOutput = @($script:hookPayload | & $pythonPath @pythonArgs (Join-Path $scriptDir "pre-tool-use.py"))
        $fallbackStatus = $LASTEXITCODE
    } finally {
        if ($null -eq $previousFallback) {
            Remove-Item Env:SULDE_CODEX_FALLBACK_ONLY -ErrorAction SilentlyContinue
        } else {
            $env:SULDE_CODEX_FALLBACK_ONLY = $previousFallback
        }
    }
    if ($fallbackStatus -eq 0) {
        $fallbackText = $fallbackOutput -join [Environment]::NewLine
        if (-not [string]::IsNullOrEmpty($fallbackText)) {
            [Console]::Out.WriteLine($fallbackText)
        }
        return
    }
    [Console]::Out.WriteLine('{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Sulde PreToolUse fallback failed; this action was not executed."}}')
}

$suldeRoot = $env:SULDE_HOME
if (-not $suldeRoot) {
    $userProfile = [Environment]::GetFolderPath("UserProfile")
    $neutralKb = Join-Path $userProfile ".sulde/data/kb"
    if ($env:SULDE_KB_HOME -and $env:SULDE_KB_HOME -ne $neutralKb) {
        # Explicit portable/test KB homes keep their self-contained launcher tree.
        $suldeRoot = $env:SULDE_KB_HOME
    } else {
        $suldeRoot = Join-Path $userProfile ".sulde"
    }
}
$bridge = Join-Path $suldeRoot "bin/intent-guardian"
$bridgeEntry = Get-Item -LiteralPath $bridge -Force -ErrorAction SilentlyContinue
if ($env:SULDE_HOOK_RUNTIME_REBOUND -ne "1" -and $null -ne $bridgeEntry) {
    if ($pythonPath -and -not $bridgeEntry.PSIsContainer) {
        & $pythonPath @pythonArgs $bridge "codex-hook-probe" $Hook *> $null
        if ($LASTEXITCODE -eq 0) {
            $env:SULDE_SESSION_PLUGIN_ROOT = Split-Path -Parent $scriptDir
            $env:SULDE_HOOK_RUNTIME_REBOUND = "1"
            $env:SULDE_INTENT_GUARDIAN = ""
            if ($Hook -eq "pre-tool-use") {
                $bridgeOutput = @(Invoke-ObservedHook -Stage "bridge" -CommandArgs (@($pythonPath) + $pythonArgs + @($bridge, "codex-hook", $Hook)))
            } else {
                $bridgeOutput = @(Invoke-ObservedHook -Stage "bridge" -CommandArgs (@($pythonPath) + $pythonArgs + @($bridge, "codex-hook", $Hook)))
            }
            $bridgeStatus = $LASTEXITCODE
            $bridgeText = $bridgeOutput -join [Environment]::NewLine
            if ($bridgeStatus -eq 0) {
                if ($Hook -ne "pre-tool-use") {
                    if (-not [string]::IsNullOrEmpty($bridgeText)) {
                        [Console]::Out.WriteLine($bridgeText)
                    }
                    exit 0
                }
                if ([string]::IsNullOrWhiteSpace($bridgeText)) {
                    exit 0
                }
                if (Test-ValidPolicyDeny -EventName $Hook -Payload $bridgeText) {
                    [Console]::Out.WriteLine($bridgeText)
                    exit 0
                }
                [Console]::Error.WriteLine("sulde: failed_closed stable hook bridge returned no valid policy decision")
                Invoke-PreToolFallback
                exit 0
            }
            if ($bridgeStatus -eq 2 -and (Test-ValidPolicyDeny -EventName $Hook -Payload $bridgeText)) {
                [Console]::Out.WriteLine($bridgeText)
                exit 0
            }
            if ($Hook -eq "pre-tool-use") {
                [Console]::Error.WriteLine("sulde: failed_closed stable hook bridge dispatch failed")
                Invoke-PreToolFallback
                exit 0
            }
            Write-NonblockingHookFailure -Stage "bridge" -ErrorKind "nonzero_exit" -ExitCode $bridgeStatus
            [Console]::Error.WriteLine("sulde: degraded_to_native_codex stable hook bridge dispatch failed")
            exit 0
        }
    }
    if ($Hook -eq "pre-tool-use") {
        [Console]::Error.WriteLine("sulde: failed_closed stable hook bridge probe failed")
        Invoke-PreToolFallback
        exit 0
    }
    Write-NonblockingHookFailure -Stage "bridge" -ErrorKind "unavailable" -ExitCode 1
    [Console]::Error.WriteLine("sulde: degraded_to_native_codex stable hook bridge probe failed")
    exit 0
}
if ($pythonPath) {
    if ($Hook -eq "pre-tool-use") {
        $adapterOutput = @(Invoke-ObservedHook -Stage "adapter" -CommandArgs (@($pythonPath) + $pythonArgs + @((Join-Path $scriptDir $scriptName))))
        $adapterStatus = $LASTEXITCODE
        $adapterText = $adapterOutput -join [Environment]::NewLine
        if ($adapterStatus -eq 0 -and [string]::IsNullOrWhiteSpace($adapterText)) {
            exit 0
        }
        if ($adapterStatus -in @(0, 2) -and (Test-ValidPolicyDeny -EventName $Hook -Payload $adapterText)) {
            [Console]::Out.WriteLine($adapterText)
            exit 0
        }
        [Console]::Error.WriteLine("sulde: failed_closed local hook adapter returned no valid policy decision")
        Invoke-PreToolFallback
        exit 0
    } else {
        Invoke-ObservedHook -Stage "adapter" -CommandArgs (@($pythonPath) + $pythonArgs + @((Join-Path $scriptDir $scriptName)))
    }
    $adapterStatus = $LASTEXITCODE
    if ($adapterStatus -ne 0) {
        Write-NonblockingHookFailure -Stage "adapter" -ErrorKind "nonzero_exit" -ExitCode $adapterStatus
        [Console]::Error.WriteLine("sulde: degraded_to_native_codex local hook adapter failed")
    }
    exit 0
}
if ($Hook -eq "pre-tool-use") {
    [Console]::Out.WriteLine('{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Sulde PreToolUse cannot start without Python 3; this action was not executed."}}')
}
[Console]::Error.WriteLine("sulde: degraded_to_native_codex local hook adapter cannot start without Python 3")
exit 0
