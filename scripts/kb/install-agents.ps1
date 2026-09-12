[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Uninstall,
    [switch]$AcceptDailyLlmInvocation,
    # Backward-compatible alias retained for existing automation.
    [switch]$AcceptDailyClaudeInvocation,
    [ValidateSet('Auto', 'Claude', 'Codex')]
    [string]$Provider = 'Auto',
    [string]$RuntimeRoot,
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$DistillAt = '09:30'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$HarvestTask = 'Sulde-Codex-Harvest'
$EmbedTask = 'Sulde-Memory-Embed'
$DistillTask = 'Sulde-Daily-Distill'
$TaskNames = @($HarvestTask, $EmbedTask, $DistillTask)
$RetiredTaskNames = @('Sulde-Claude-Harvest', 'Sulde-Claude-Distill')
$DeploymentLockName = '.deployment.lock'

function Resolve-PluginRoot {
    $selected = if ($RuntimeRoot) { $RuntimeRoot } else { $env:SULDE_RUNTIME_ROOT }
    if (-not $selected) {
        throw 'An explicit immutable -RuntimeRoot is required; mutable source/cache discovery is disabled.'
    }
    $item = Get-Item -LiteralPath $selected -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "RuntimeRoot must not be a symbolic link or junction: $selected"
    }
    return (Resolve-Path -LiteralPath $selected).Path
}

function Resolve-KbHome {
    if ($env:SULDE_KB_HOME) {
        return [IO.Path]::GetFullPath($env:SULDE_KB_HOME)
    }
    $suldeRoot = if ($env:SULDE_HOME) { $env:SULDE_HOME } else { Join-Path $HOME '.sulde' }
    return (Join-Path $suldeRoot 'data\kb')
}

function Resolve-LauncherHome([string]$KbHome) {
    if ($env:SULDE_LAUNCHER_HOME) {
        return [IO.Path]::GetFullPath($env:SULDE_LAUNCHER_HOME)
    }
    $suldeRoot = if ($env:SULDE_HOME) { $env:SULDE_HOME } else { Join-Path $HOME '.sulde' }
    $resolvedRoot = [IO.Path]::GetFullPath($suldeRoot)
    $neutralKb = [IO.Path]::GetFullPath((Join-Path $resolvedRoot 'data\kb'))
    $resolvedKb = [IO.Path]::GetFullPath($KbHome)
    if ($resolvedKb -eq $neutralKb) { return $resolvedRoot }
    return $resolvedKb
}

function Resolve-VenvTaskPython([string]$KbHome) {
    $candidate = Join-Path $KbHome 'venv\Scripts\pythonw.exe'
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        return (Resolve-Path -LiteralPath $candidate).Path
    }
    throw "Sulde KB windowless Python not found: $candidate. Recreate the Windows venv, then run this installer again."
}

function Resolve-CodexNativeExecutable([string]$Source) {
    if (-not $Source) { return $null }
    $commandRoot = Split-Path -Parent $Source
    if (-not $commandRoot) { return $null }
    $scopeRoots = @(
        (Join-Path $commandRoot 'node_modules\@openai\codex\node_modules\@openai'),
        (Join-Path $commandRoot 'node_modules\@openai')
    )
    $binaries = @()
    foreach ($scopeRoot in $scopeRoots) {
        if (-not (Test-Path -LiteralPath $scopeRoot -PathType Container)) { continue }
        $packages = Get-ChildItem `
            -LiteralPath $scopeRoot `
            -Directory `
            -Filter 'codex-win32-*' `
            -ErrorAction SilentlyContinue
        foreach ($package in $packages) {
            $vendor = Join-Path $package.FullName 'vendor'
            if (-not (Test-Path -LiteralPath $vendor -PathType Container)) { continue }
            $binaries += Get-ChildItem `
                -LiteralPath $vendor `
                -Recurse `
                -File `
                -Filter 'codex.exe' `
                -ErrorAction SilentlyContinue |
                Where-Object { $_.Directory.Name -eq 'bin' }
        }
    }
    $unique = @($binaries | Sort-Object FullName -Unique)
    if ($unique.Count -eq 1) {
        return (Resolve-Path -LiteralPath $unique[0].FullName).Path
    }
    $architecture = switch (
        [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    ) {
        'X64' { 'x64' }
        'Arm64' { 'arm64' }
        default { $null }
    }
    if ($architecture) {
        $matching = @(
            $unique | Where-Object {
                $_.FullName -like "*\codex-win32-$architecture\*"
            }
        )
        if ($matching.Count -eq 1) {
            return (Resolve-Path -LiteralPath $matching[0].FullName).Path
        }
    }
    return $null
}

function ConvertTo-SpawnableProviderPath([string]$RuntimeProvider, [string]$Source) {
    if (-not $Source) { return $null }
    $candidate = if (Test-Path -LiteralPath $Source -PathType Leaf) {
        (Resolve-Path -LiteralPath $Source).Path
    } else {
        $Source
    }
    $extension = [IO.Path]::GetExtension($candidate).ToLowerInvariant()
    if ($RuntimeProvider -eq 'Codex') {
        if ($extension -eq '.exe') { return $candidate }
        return Resolve-CodexNativeExecutable $candidate
    }
    if ($extension -eq '.ps1') {
        $cmdSibling = [IO.Path]::ChangeExtension($candidate, '.cmd')
        if (Test-Path -LiteralPath $cmdSibling -PathType Leaf) {
            return (Resolve-Path -LiteralPath $cmdSibling).Path
        }
        return $null
    }
    return $candidate
}

function Resolve-ProviderExecutable([string]$RuntimeProvider) {
    $override = if ($RuntimeProvider -eq 'Claude') { $env:SULDE_CLAUDE_EXE } else { $env:SULDE_CODEX_EXE }
    if ($override) {
        if (Test-Path -LiteralPath $override -PathType Leaf) {
            $resolvedOverride = ConvertTo-SpawnableProviderPath $RuntimeProvider $override
            if ($resolvedOverride) { return $resolvedOverride }
        }
        $overrideCommand = Get-Command $override -ErrorAction SilentlyContinue
        if ($overrideCommand) {
            $resolvedOverride = ConvertTo-SpawnableProviderPath $RuntimeProvider $overrideCommand.Source
            if ($resolvedOverride) { return $resolvedOverride }
        }
        return $null
    }
    $commandName = $RuntimeProvider.ToLowerInvariant()
    $currentCommand = Get-Command $commandName -ErrorAction SilentlyContinue
    if ($currentCommand) {
        $resolvedCurrent = ConvertTo-SpawnableProviderPath $RuntimeProvider $currentCommand.Source
        if ($resolvedCurrent) { return $resolvedCurrent }
        if ($RuntimeProvider -eq 'Codex') { return $null }
    }
    foreach ($candidate in @("$commandName.cmd", "$commandName.exe", "$commandName.bat")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) {
            $resolvedCandidate = ConvertTo-SpawnableProviderPath $RuntimeProvider $command.Source
            if ($resolvedCandidate) { return $resolvedCandidate }
        }
    }
    return $null
}

function Resolve-RuntimeProvider([string]$Requested) {
    if ($Requested -ne 'Auto') {
        $executable = Resolve-ProviderExecutable $Requested
        if (-not $executable) {
            throw "Selected provider $Requested is unavailable; Sulde will not fall back to another provider."
        }
        return [PSCustomObject]@{ Name = $Requested.ToLowerInvariant(); Executable = $executable }
    }

    $codexEvidence = [bool]($env:CODEX_THREAD_ID -or $env:CODEX_CI)
    $claudeEvidence = [bool]($env:CLAUDECODE -or $env:CLAUDE_CODE_ENTRYPOINT -or $env:CLAUDE_SESSION_ID)
    if ($codexEvidence -xor $claudeEvidence) {
        $detected = if ($codexEvidence) { 'Codex' } else { 'Claude' }
        $executable = Resolve-ProviderExecutable $detected
        if (-not $executable) {
            throw "Detected $detected host but its executable is unavailable; cross-provider fallback is disabled."
        }
        return [PSCustomObject]@{ Name = $detected.ToLowerInvariant(); Executable = $executable }
    }

    $claude = Resolve-ProviderExecutable 'Claude'
    $codex = Resolve-ProviderExecutable 'Codex'
    if ($claude -and -not $codex) {
        return [PSCustomObject]@{ Name = 'claude'; Executable = $claude }
    }
    if ($codex -and -not $claude) {
        return [PSCustomObject]@{ Name = 'codex'; Executable = $codex }
    }
    throw 'Auto provider is ambiguous; pass -Provider Claude or -Provider Codex.'
}

function Get-SuldeTasks {
    return @(Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.TaskName -like 'Sulde-*' })
}

function Assert-SuldeTaskInventory($Tasks) {
    $allowed = @($TaskNames + $RetiredTaskNames)
    $unknown = @(
        $Tasks |
        Where-Object { $_.TaskName -notin $allowed -or [string]$_.TaskPath -cne '\' } |
        ForEach-Object { "$($_.TaskPath)$($_.TaskName)" } |
        Sort-Object -Unique
    )
    $duplicates = @(
        $Tasks |
        Group-Object TaskName |
        Where-Object { $_.Count -ne 1 } |
        ForEach-Object { $_.Name }
    )
    $unknown = @($unknown + $duplicates | Sort-Object -Unique)
    if ($unknown.Count -gt 0) {
        throw "unknown Sulde task blocks reconciliation: $($unknown -join ', ')"
    }
    return @(
        $Tasks |
        Where-Object { $_.TaskName -in $RetiredTaskNames } |
        ForEach-Object { $_.TaskName } |
        Sort-Object -Unique
    )
}

function Remove-SuldeTasks {
    $existingTasks = Get-SuldeTasks
    [void](Assert-SuldeTaskInventory $existingTasks)
    foreach ($taskName in @($TaskNames + $RetiredTaskNames)) {
        $existing = @($existingTasks | Where-Object { $_.TaskName -eq $taskName })
        if ($DryRun) {
            Write-Output "DRY-RUN remove task: $taskName existing=$($existing.Count -gt 0)"
        } elseif ($existing.Count -gt 0) {
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
            Write-Output "Removed task: $taskName"
        }
    }
}

function Enter-DeploymentLock([string]$KbHome) {
    $path = Join-Path $KbHome $DeploymentLockName
    try {
        New-Item -ItemType Directory -Path $path -ErrorAction Stop | Out-Null
    } catch {
        throw "another plugin or scheduler deployment owns $path"
    }
    @{ pid = $PID; operation = 'windows-task-reconcile' } |
        ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $path 'owner.json') -Encoding UTF8
    return $path
}

function Exit-DeploymentLock([string]$Path) {
    if (-not $Path) { return }
    Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
}

function Save-RetiredState([string]$RetiredRoot, [string]$SnapshotRoot) {
    if (Test-Path -LiteralPath $SnapshotRoot) {
        throw "Retired-state snapshot already exists: $SnapshotRoot"
    }
    New-Item -ItemType Directory -Path $SnapshotRoot -Force | Out-Null
    $rootPresent = Test-Path -LiteralPath $RetiredRoot -PathType Container
    if ((Test-Path -LiteralPath $RetiredRoot) -and -not $rootPresent) {
        throw "Windows retired-state root is not a directory: $RetiredRoot"
    }
    $aclRecords = @()
    if ($rootPresent) {
        $rootItem = Get-Item -LiteralPath $RetiredRoot -Force
        $items = @($rootItem) + @(Get-ChildItem -LiteralPath $RetiredRoot -Force -Recurse)
        $fullRoot = [IO.Path]::GetFullPath($rootItem.FullName).TrimEnd('\')
        foreach ($item in $items) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Windows retired-state must not contain a symbolic link or junction: $($item.FullName)"
            }
            $relative = if ($item.FullName.Length -eq $fullRoot.Length) {
                ''
            } else {
                $item.FullName.Substring($fullRoot.Length).TrimStart('\')
            }
            $security = Get-Acl -LiteralPath $item.FullName
            $aclRecords += @{
                relative = $relative
                kind = if ($item.PSIsContainer) { 'directory' } else { 'file' }
                dacl = $security.GetSecurityDescriptorSddlForm(
                    [Security.AccessControl.AccessControlSections]::Access
                )
            }
        }
        Copy-Item -LiteralPath $RetiredRoot -Destination (Join-Path $SnapshotRoot 'tree') -Recurse -Force
    }
    @{
        schema = 'sulde-windows-retired-snapshot-v1'
        present = $rootPresent
        acl = @($aclRecords)
    } | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $SnapshotRoot 'manifest.json') -Encoding UTF8
}

function Restore-RetiredState([string]$RetiredRoot, [string]$SnapshotRoot) {
    $manifestPath = Join-Path $SnapshotRoot 'manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw 'Windows retired-state transaction manifest is missing.'
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$manifest.schema -cne 'sulde-windows-retired-snapshot-v1') {
        throw 'Windows retired-state transaction manifest is invalid.'
    }
    if (Test-Path -LiteralPath $RetiredRoot) {
        $current = Get-Item -LiteralPath $RetiredRoot -Force
        if ($current.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Refusing to replace retired-state symbolic link or junction: $RetiredRoot"
        }
        if (-not $current.PSIsContainer) {
            throw "Refusing to replace non-directory retired state: $RetiredRoot"
        }
        Remove-Item -LiteralPath $RetiredRoot -Recurse -Force
    }
    if (-not [bool]$manifest.present) {
        return
    }
    $savedTree = Join-Path $SnapshotRoot 'tree'
    if (-not (Test-Path -LiteralPath $savedTree -PathType Container)) {
        throw 'Windows retired-state transaction tree is missing.'
    }
    Copy-Item -LiteralPath $savedTree -Destination $RetiredRoot -Recurse -Force
    $aclRecords = @($manifest.acl | Sort-Object { ([string]$_.relative).Length } -Descending)
    foreach ($record in $aclRecords) {
        $target = if ([string]$record.relative) {
            Join-Path $RetiredRoot ([string]$record.relative)
        } else {
            $RetiredRoot
        }
        if (-not (Test-Path -LiteralPath $target)) {
            throw "Windows retired-state ACL target is missing: $target"
        }
        $security = if ([string]$record.kind -ceq 'directory') {
            New-Object System.Security.AccessControl.DirectorySecurity
        } else {
            New-Object System.Security.AccessControl.FileSecurity
        }
        $security.SetSecurityDescriptorSddlForm(
            [string]$record.dacl,
            [Security.AccessControl.AccessControlSections]::Access
        )
        Set-Acl -LiteralPath $target -AclObject $security
    }
}

function Save-Transaction(
    [string]$Root,
    [string]$RunnerPath,
    [string]$OwnerPath,
    [string]$DeploymentPath,
    [string]$LauncherPath,
    [string]$RetiredRoot,
    $Tasks
) {
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    $files = @{
        runner = $RunnerPath
        owner = $OwnerPath
        deployment = $DeploymentPath
        launcher = $LauncherPath
    }
    $presence = @{}
    foreach ($entry in $files.GetEnumerator()) {
        $present = Test-Path -LiteralPath $entry.Value -PathType Leaf
        $presence[$entry.Key] = $present
        if ($present) {
            Copy-Item -LiteralPath $entry.Value -Destination (Join-Path $Root "$($entry.Key).snapshot") -Force
        }
    }
    $presence | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Root 'files.json') -Encoding UTF8
    $taskIndex = @()
    foreach ($task in $Tasks) {
        $safeName = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($task.TaskName)).Replace('/', '_')
        $xmlPath = Join-Path $Root "$safeName.xml"
        Export-ScheduledTask -TaskName $task.TaskName | Set-Content -LiteralPath $xmlPath -Encoding Unicode
        $taskIndex += @{ name = $task.TaskName; xml = $xmlPath }
    }
    $taskIndex | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Root 'tasks.json') -Encoding UTF8
    Save-RetiredState $RetiredRoot (Join-Path $Root 'retired-state')
}

function Restore-Transaction(
    [string]$Root,
    [string]$RunnerPath,
    [string]$OwnerPath,
    [string]$DeploymentPath,
    [string]$LauncherPath,
    [string]$RetiredRoot
) {
    foreach ($task in @(Get-SuldeTasks)) {
        if ($task.TaskName -in @($TaskNames + $RetiredTaskNames)) {
            Unregister-ScheduledTask -TaskName $task.TaskName -Confirm:$false -ErrorAction SilentlyContinue
        }
    }
    $taskIndex = @(Get-Content -LiteralPath (Join-Path $Root 'tasks.json') -Raw -Encoding UTF8 | ConvertFrom-Json)
    foreach ($record in $taskIndex) {
        $xml = Get-Content -LiteralPath $record.xml -Raw -Encoding Unicode
        Register-ScheduledTask -TaskName $record.name -Xml $xml -Force | Out-Null
    }
    Restore-RetiredState $RetiredRoot (Join-Path $Root 'retired-state')
    $presence = Get-Content -LiteralPath (Join-Path $Root 'files.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    # The owner is restored last so rollback cannot expose active/ready before
    # task XML, retired evidence and every other generation authority are exact.
    $files = @(
        @{ key = 'runner'; path = $RunnerPath },
        @{ key = 'deployment'; path = $DeploymentPath },
        @{ key = 'launcher'; path = $LauncherPath },
        @{ key = 'owner'; path = $OwnerPath }
    )
    foreach ($entry in $files) {
        $wasPresent = [bool]$presence.PSObject.Properties[$entry.key].Value
        if ($wasPresent) {
            Copy-Item -LiteralPath (Join-Path $Root "$($entry.key).snapshot") -Destination $entry.path -Force
        } else {
            Remove-Item -LiteralPath $entry.path -Force -ErrorAction SilentlyContinue
        }
    }
}

function Read-JsonObject([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Generation authority is missing: $Path"
    }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Generation authority must not be a symbolic link or junction: $Path"
    }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Assert-GenerationField($Payload, [string]$Field, [string]$Expected, [string]$Authority) {
    if ([string]$Payload.$Field -cne $Expected) {
        throw "$Authority generation mismatch for ${Field}: '$($Payload.$Field)' != '$Expected'"
    }
}

function Write-RuntimeOwner(
    [string]$Path,
    [string]$Status,
    [bool]$OperationalReady,
    [string]$Runtime,
    [string]$Digest,
    [string]$Generation,
    [string]$RuntimeProvider,
    [string]$Executable,
    [string]$RunnerSha256,
    $TaskReadback
) {
    $temporary = "$Path.tmp"
    @{
        schema_version = 2
        status = $Status
        installation_status = 'installed_degraded'
        operational_ready = $OperationalReady
        provider = $RuntimeProvider
        executable = $Executable
        source_root = $Runtime
        runtime_root = $Runtime
        runtime_tree_sha256 = $Digest
        generation = $Generation
        scheduler_runner_sha256 = $RunnerSha256
        managed_labels = $TaskNames
        retired_labels = $RetiredTaskNames
        task_readback = @($TaskReadback)
        scheduler = 'windows-task-scheduler'
        installed_at = [DateTime]::UtcNow.ToString('o')
    } | ConvertTo-Json | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

if ($Uninstall) {
    $uninstallHome = Resolve-KbHome
    New-Item -ItemType Directory -Path $uninstallHome -Force | Out-Null
    $uninstallLock = $null
    if (-not $DryRun) { $uninstallLock = Enter-DeploymentLock $uninstallHome }
    try {
        Remove-SuldeTasks
        $ownerPath = Join-Path $uninstallHome 'runtime-owner.json'
        if ($DryRun) {
            Write-Output "DRY-RUN remove scheduler owner: $ownerPath existing=$(Test-Path -LiteralPath $ownerPath)"
        } elseif (Test-Path -LiteralPath $ownerPath -PathType Leaf) {
            Remove-Item -LiteralPath $ownerPath -Force
            Write-Output "Removed scheduler owner: $ownerPath"
        }
    } finally {
        Exit-DeploymentLock $uninstallLock
    }
    exit 0
}

if (-not ($AcceptDailyLlmInvocation -or $AcceptDailyClaudeInvocation)) {
    throw 'Daily Distill invokes the selected host LLM with up to 40,000 characters of redacted local memory. Re-run with -AcceptDailyLlmInvocation after reviewing this data-egress impact.'
}

$resolvedProvider = Resolve-RuntimeProvider $Provider
$runtimeProvider = $resolvedProvider.Name
$providerExecutable = $resolvedProvider.Executable
$pluginRoot = Resolve-PluginRoot
$kbHome = Resolve-KbHome
$launcherHome = Resolve-LauncherHome $kbHome
$taskPython = Resolve-VenvTaskPython $kbHome
$taskSource = Join-Path $pluginRoot 'scripts\kb\windows-task.py'
if (-not (Test-Path -LiteralPath $taskSource -PathType Leaf)) {
    throw "Windows task runner not found: $taskSource"
}
$runnerSha256 = (Get-FileHash -LiteralPath $taskSource -Algorithm SHA256).Hash.ToLowerInvariant()
$verificationText = & $taskPython $taskSource `
    --kb-home $kbHome `
    --runtime-root $pluginRoot `
    verify-staged
if ($LASTEXITCODE -ne 0) {
    throw 'Immutable Windows runtime verification failed.'
}
$runtimeMeta = $verificationText | ConvertFrom-Json
$runtimeGeneration = [string]$runtimeMeta.generation
$runtimeTreeSha256 = [string]$runtimeMeta.runtime_tree_sha256
$deploymentPath = Join-Path $kbHome 'deployment-generation.json'
$launcherPath = Join-Path $launcherHome 'bin\.sulde-launchers.json'
$deployment = Read-JsonObject $deploymentPath
$launcher = Read-JsonObject $launcherPath
Assert-GenerationField $deployment 'runtime_root' $pluginRoot 'Deployment descriptor'
Assert-GenerationField $deployment 'runtime_tree_sha256' $runtimeTreeSha256 'Deployment descriptor'
Assert-GenerationField $deployment 'generation' $runtimeGeneration 'Deployment descriptor'
Assert-GenerationField $launcher 'source_root' $pluginRoot 'Stable launcher manifest'
Assert-GenerationField $launcher 'runtime_tree_sha256' $runtimeTreeSha256 'Stable launcher manifest'
Assert-GenerationField $launcher 'generation' $runtimeGeneration 'Stable launcher manifest'
$bin = Join-Path $kbHome 'bin'
$taskRunner = Join-Path $bin 'sulde-windows-task.py'
$existingSuldeTasks = Get-SuldeTasks
$retiredTasks = @(Assert-SuldeTaskInventory $existingSuldeTasks)
$distillTime = [datetime]::ParseExact(
    $DistillAt,
    'HH:mm',
    [Globalization.CultureInfo]::InvariantCulture
)

Write-Output "Daily Distill data-egress accepted: $runtimeProvider receives at most 40,000 characters of redacted local memory per scheduled run."
Write-Output "Runtime provider: $runtimeProvider ($providerExecutable)"
Write-Output "Runtime source: $pluginRoot"
Write-Output "Runtime generation: $runtimeGeneration"
Write-Output "Stable task runner: $taskRunner"
Write-Output "Stable task runner sha256: $runnerSha256"
Write-Output "Retired tasks: $($retiredTasks -join ', ')"
Write-Output "Task Python: $taskPython"
Write-Output "Task: $HarvestTask every 30 minutes"
Write-Output "Task: $EmbedTask every 5 minutes"
Write-Output "Task: $DistillTask daily at $DistillAt"

$harvestAction = New-ScheduledTaskAction `
    -Execute $taskPython `
    -Argument "`"$taskRunner`" --kb-home `"$kbHome`" --runtime-root `"$pluginRoot`" --generation `"$runtimeGeneration`" --runner-sha256 `"$runnerSha256`" --provider `"$runtimeProvider`" --provider-executable `"$providerExecutable`" harvest" `
    -WorkingDirectory $kbHome
$distillAction = New-ScheduledTaskAction `
    -Execute $taskPython `
    -Argument "`"$taskRunner`" --kb-home `"$kbHome`" --runtime-root `"$pluginRoot`" --generation `"$runtimeGeneration`" --runner-sha256 `"$runnerSha256`" --provider `"$runtimeProvider`" --provider-executable `"$providerExecutable`" distill" `
    -WorkingDirectory $kbHome
$embedAction = New-ScheduledTaskAction `
    -Execute $taskPython `
    -Argument "`"$taskRunner`" --kb-home `"$kbHome`" --runtime-root `"$pluginRoot`" --generation `"$runtimeGeneration`" --runner-sha256 `"$runnerSha256`" --provider `"$runtimeProvider`" --provider-executable `"$providerExecutable`" embed" `
    -WorkingDirectory $kbHome
Write-Output "Harvest action executable: $($harvestAction.Execute)"
Write-Output "Memory embed action executable: $($embedAction.Execute)"
Write-Output "Distill action executable: $($distillAction.Execute)"

if ($DryRun) {
    Write-Output 'DRY-RUN complete: no files copied and no scheduled tasks changed.'
    exit 0
}

New-Item -ItemType Directory -Path $bin -Force | Out-Null
$ownerPath = Join-Path $kbHome 'runtime-owner.json'
$lockPath = Enter-DeploymentLock $kbHome
$transactionRoot = Join-Path $lockPath 'windows-transaction'
$retiredRoot = Join-Path $kbHome '.sulde-retired\windows-tasks'
$installedTasks = @()
$transactionSaved = $false
try {
    # Re-read all mutable authorities under the shared deployment lock.
    $lockedTasks = Get-SuldeTasks
    $retiredTasks = @(Assert-SuldeTaskInventory $lockedTasks)
    $deployment = Read-JsonObject $deploymentPath
    $launcher = Read-JsonObject $launcherPath
    Assert-GenerationField $deployment 'runtime_root' $pluginRoot 'Deployment descriptor'
    Assert-GenerationField $deployment 'runtime_tree_sha256' $runtimeTreeSha256 'Deployment descriptor'
    Assert-GenerationField $deployment 'generation' $runtimeGeneration 'Deployment descriptor'
    Assert-GenerationField $launcher 'source_root' $pluginRoot 'Stable launcher manifest'
    Assert-GenerationField $launcher 'runtime_tree_sha256' $runtimeTreeSha256 'Stable launcher manifest'
    Assert-GenerationField $launcher 'generation' $runtimeGeneration 'Stable launcher manifest'

    Save-Transaction $transactionRoot $taskRunner $ownerPath $deploymentPath $launcherPath $retiredRoot $lockedTasks
    $transactionSaved = $true
    Write-RuntimeOwner $ownerPath 'reconciling' $false $pluginRoot $runtimeTreeSha256 $runtimeGeneration $runtimeProvider $providerExecutable $runnerSha256 @()
    Copy-Item -LiteralPath $taskSource -Destination $taskRunner -Force
    if ((Get-Item -LiteralPath $taskRunner -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Stable Windows task runner must not be a symbolic link or junction.'
    }
    if ((Get-FileHash -LiteralPath $taskRunner -Algorithm SHA256).Hash.ToLowerInvariant() -cne $runnerSha256) {
        throw 'Stable Windows task runner copy did not preserve its exact digest.'
    }
    $deployment | Add-Member -NotePropertyName scheduler_runner -NotePropertyValue $taskRunner -Force
    $deployment | Add-Member -NotePropertyName scheduler_runner_sha256 -NotePropertyValue $runnerSha256 -Force
    $launcher | Add-Member -NotePropertyName scheduler_runner -NotePropertyValue $taskRunner -Force
    $launcher | Add-Member -NotePropertyName scheduler_runner_sha256 -NotePropertyValue $runnerSha256 -Force
    $deployment | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath "$deploymentPath.tmp" -Encoding UTF8
    Move-Item -LiteralPath "$deploymentPath.tmp" -Destination $deploymentPath -Force
    $launcher | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath "$launcherPath.tmp" -Encoding UTF8
    Move-Item -LiteralPath "$launcherPath.tmp" -Destination $launcherPath -Force
    New-Item -ItemType Directory -Path $retiredRoot -Force | Out-Null
    foreach ($retiredName in $retiredTasks) {
        $archive = Join-Path $retiredRoot "$retiredName.xml"
        Export-ScheduledTask -TaskName $retiredName | Set-Content -LiteralPath $archive -Encoding Unicode
        Unregister-ScheduledTask -TaskName $retiredName -Confirm:$false
        @{
            schema = 'sulde-retired-scheduler-actor-v1'
            status = 'retired'
            label = $retiredName
            replacement = 'immutable-generation-owner'
        } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $retiredRoot "$retiredName.tombstone.json") -Encoding UTF8
    }

    $userId = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
    $harvestTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 30)
    $harvestSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
    Register-ScheduledTask -TaskName $HarvestTask -Action $harvestAction -Trigger $harvestTrigger -Principal $principal -Settings $harvestSettings -Description 'Incrementally harvest Codex rollouts into the local Sulde memory database every 30 minutes.' -Force | Out-Null

    $embedTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
    $embedSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 3)
    Register-ScheduledTask -TaskName $EmbedTask -Action $embedAction -Trigger $embedTrigger -Principal $principal -Settings $embedSettings -Description 'Embed a bounded batch of pending Sulde memories every five minutes.' -Force | Out-Null

    $distillTrigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.Add($distillTime.TimeOfDay))
    $distillSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName $DistillTask -Action $distillAction -Trigger $distillTrigger -Principal $principal -Settings $distillSettings -Description "Distill recent Sulde session memories through the selected $runtimeProvider runtime once daily." -Force | Out-Null

    $allInstalled = Get-SuldeTasks
    [void](Assert-SuldeTaskInventory $allInstalled)
    $installedTasks = @($allInstalled | Where-Object { $_.TaskName -in $TaskNames })
    $installedNames = @($installedTasks | ForEach-Object { $_.TaskName } | Sort-Object -Unique)
    $expectedNames = @($TaskNames | Sort-Object -Unique)
    if (($installedNames -join "`n") -cne ($expectedNames -join "`n")) {
        throw 'Scheduled task inventory does not match the declared runtime owner.'
    }
    $expectedActions = @{ $HarvestTask = $harvestAction; $EmbedTask = $embedAction; $DistillTask = $distillAction }
    $taskReadback = @()
    foreach ($task in $installedTasks) {
        $actions = @($task.Actions)
        $expectedAction = $expectedActions[$task.TaskName]
        if ($actions.Count -ne 1 -or
            [string]$actions[0].Execute -cne [string]$expectedAction.Execute -or
            [string]$actions[0].Arguments -cne [string]$expectedAction.Arguments -or
            [string]$actions[0].WorkingDirectory -cne [string]$expectedAction.WorkingDirectory) {
            throw "Scheduled task action readback mismatch: $($task.TaskName)"
        }
        foreach ($binding in @($pluginRoot, $runtimeGeneration, $runnerSha256)) {
            if ([string]$actions[0].Arguments -cnotlike "*$binding*") {
                throw "Scheduled task action lacks runtime/generation/runner binding: $($task.TaskName)"
            }
        }
        $info = Get-ScheduledTaskInfo -TaskName $task.TaskName -ErrorAction Stop
        $taskReadback += @{
            task_name = $task.TaskName
            action_execute = [string]$actions[0].Execute
            action_arguments = [string]$actions[0].Arguments
            runtime_root = $pluginRoot
            generation = $runtimeGeneration
            runner_sha256 = $runnerSha256
            LastTaskResult = [int64]$info.LastTaskResult
        }
    }
    # Registration is installed truth only. A later live run may promote operational readiness.
    Write-RuntimeOwner $ownerPath 'active' $false $pluginRoot $runtimeTreeSha256 $runtimeGeneration $runtimeProvider $providerExecutable $runnerSha256 $taskReadback
} catch {
    $reconcileFailure = $_.Exception.Message
    if (-not $transactionSaved) {
        throw "Windows scheduler reconcile aborted before mutation: $reconcileFailure"
    }
    try {
        Restore-Transaction $transactionRoot $taskRunner $ownerPath $deploymentPath $launcherPath $retiredRoot
    } catch {
        throw "FAIL CLOSED: Windows scheduler reconcile and rollback both failed; active/ready must not be reported. reconcile=$reconcileFailure rollback=$($_.Exception.Message)"
    }
    throw "Windows scheduler reconcile rolled back to the complete previous generation: $reconcileFailure"
} finally {
    Exit-DeploymentLock $lockPath
}

Write-Output "Scheduler ownership recorded: $ownerPath provider=$runtimeProvider generation=$runtimeGeneration operational_ready=false"
$installedTasks | Select-Object TaskName, State, TaskPath
