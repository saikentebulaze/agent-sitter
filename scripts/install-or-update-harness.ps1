[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ProjectRoot,

    [ValidateNotNullOrEmpty()]
    [string]$HarnessBranch = "master",

    [ValidateNotNullOrEmpty()]
    [string]$PythonCommand = "python",

    [switch]$InitializeGit,
    [switch]$SkipSourceUpdate,
    [switch]$SkipHarnessTests,
    [switch]$AdoptExisting,
    [switch]$ForceTrustProject,
    [switch]$NoTrustProject
)

$ErrorActionPreference = "Stop"

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit code $LASTEXITCODE)"
    }
}

function Invoke-NativeCapture {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    $output = & $FilePath @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        $output | ForEach-Object { Write-Host $_ }
        throw "$FailureMessage (exit code $LASTEXITCODE)"
    }
    return (($output | ForEach-Object { "$_" }) -join "`n").Trim()
}

function Get-YamlScalar {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Key
    )

    $pattern = '^\s*' + [regex]::Escape($Key) + '\s*:\s*(.+?)\s*$'
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        if ($line -match $pattern) {
            return $Matches[1].Trim('"', "'")
        }
    }
    throw "Missing YAML key '$Key' in $Path"
}

if ($ForceTrustProject -and $NoTrustProject) {
    throw "-ForceTrustProject and -NoTrustProject cannot be used together."
}

$HarnessRepo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not (Test-Path -LiteralPath $ProjectRoot)) {
    if (-not $InitializeGit) {
        throw "ProjectRoot does not exist: $ProjectRoot. Use -InitializeGit to create it as a Git repository."
    }
    New-Item -ItemType Directory -Path $ProjectRoot -Force | Out-Null
}

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

$gitTopLevel = $null
try {
    $gitTopLevel = Invoke-NativeCapture `
        -FilePath "git" `
        -Arguments @("-C", $ProjectRoot, "rev-parse", "--show-toplevel") `
        -FailureMessage "Target project is not a Git worktree"
}
catch {
    if (-not $InitializeGit) {
        throw
    }
    Invoke-NativeCommand `
        -FilePath "git" `
        -Arguments @("-C", $ProjectRoot, "init") `
        -FailureMessage "Failed to initialize target Git repository"
    $gitTopLevel = Invoke-NativeCapture `
        -FilePath "git" `
        -Arguments @("-C", $ProjectRoot, "rev-parse", "--show-toplevel") `
        -FailureMessage "Failed to resolve initialized Git worktree"
}

$resolvedGitTopLevel = (Resolve-Path -LiteralPath $gitTopLevel).Path
if ($resolvedGitTopLevel -ne $ProjectRoot) {
    throw "ProjectRoot must be the Git worktree root. Resolved root: $resolvedGitTopLevel"
}

$trackedStatusBefore = Invoke-NativeCapture `
    -FilePath "git" `
    -Arguments @("-C", $ProjectRoot, "status", "--short", "--untracked-files=no") `
    -FailureMessage "Failed to read target project status"

if (-not $SkipSourceUpdate) {
    $harnessStatus = Invoke-NativeCapture `
        -FilePath "git" `
        -Arguments @("-C", $HarnessRepo, "status", "--short") `
        -FailureMessage "Failed to read Harness repository status"
    if ($harnessStatus) {
        throw "Harness repository has local changes. Commit, stash, or rerun with -SkipSourceUpdate.`n$harnessStatus"
    }

    Invoke-NativeCommand `
        -FilePath "git" `
        -Arguments @("-C", $HarnessRepo, "fetch", "origin") `
        -FailureMessage "Failed to fetch Harness repository"
    Invoke-NativeCommand `
        -FilePath "git" `
        -Arguments @("-C", $HarnessRepo, "switch", $HarnessBranch) `
        -FailureMessage "Failed to switch Harness branch to $HarnessBranch"
    Invoke-NativeCommand `
        -FilePath "git" `
        -Arguments @("-C", $HarnessRepo, "pull", "--ff-only", "origin", $HarnessBranch) `
        -FailureMessage "Failed to fast-forward Harness branch $HarnessBranch"
}

$HarnessHead = Invoke-NativeCapture `
    -FilePath "git" `
    -Arguments @("-C", $HarnessRepo, "rev-parse", "HEAD") `
    -FailureMessage "Failed to resolve Harness HEAD"
Write-Host "Harness HEAD: $HarnessHead"

$Requirements = Join-Path $HarnessRepo "runtime\requirements.txt"
if (Test-Path -LiteralPath $Requirements) {
    Invoke-NativeCommand `
        -FilePath $PythonCommand `
        -Arguments @("-m", "pip", "install", "-r", $Requirements) `
        -FailureMessage "Failed to install Harness Python requirements"
}

if (-not $SkipHarnessTests) {
    Invoke-NativeCommand `
        -FilePath $PythonCommand `
        -Arguments @("-m", "unittest", "discover", "-s", (Join-Path $HarnessRepo "tests"), "-v") `
        -FailureMessage "Harness repository tests failed"
}

$InstallScript = Join-Path $HarnessRepo "install.py"
$installArguments = @(
    $InstallScript,
    "--project", $ProjectRoot,
    "--reinstall"
)

if ($AdoptExisting) {
    $installArguments += "--adopt-existing"
}
if ($ForceTrustProject) {
    $installArguments += "--force-trust-project"
}
elseif (-not $NoTrustProject) {
    $installArguments += "--trust-project"
}

Write-Host "Running Harness installation dry-run..."
Invoke-NativeCommand `
    -FilePath $PythonCommand `
    -Arguments ($installArguments + "--dry-run") `
    -FailureMessage "Harness installation dry-run failed"

Write-Host "Installing or upgrading Harness..."
Invoke-NativeCommand `
    -FilePath $PythonCommand `
    -Arguments $installArguments `
    -FailureMessage "Harness installation failed"

$InstalledHarness = Join-Path $ProjectRoot ".harness\sitter"
$Runtime = Join-Path $InstalledHarness "runtime"
$InstalledLock = Join-Path $InstalledHarness "manifest-lock.yaml"

Invoke-NativeCommand `
    -FilePath $PythonCommand `
    -Arguments @((Join-Path $HarnessRepo "check.py"), "--project", $ProjectRoot) `
    -FailureMessage "Harness installation check failed"
Invoke-NativeCommand `
    -FilePath $PythonCommand `
    -Arguments @((Join-Path $Runtime "self_check.py"), "--project", $ProjectRoot) `
    -FailureMessage "Harness self-check failed"
Invoke-NativeCommand `
    -FilePath $PythonCommand `
    -Arguments @((Join-Path $Runtime "work.py"), "--help") `
    -FailureMessage "Harness work CLI discovery failed"
Invoke-NativeCommand `
    -FilePath $PythonCommand `
    -Arguments @((Join-Path $Runtime "delegation_runtime.py"), "--help") `
    -FailureMessage "Harness delegation runtime discovery failed"

$sourceVersion = Get-YamlScalar `
    -Path (Join-Path $HarnessRepo "manifest.yaml") `
    -Key "version"
$installedVersion = Get-YamlScalar `
    -Path $InstalledLock `
    -Key "version"
if ($sourceVersion -ne $installedVersion) {
    throw "Installed Harness version $installedVersion does not match source version $sourceVersion."
}

$trackedStatusAfter = Invoke-NativeCapture `
    -FilePath "git" `
    -Arguments @("-C", $ProjectRoot, "status", "--short", "--untracked-files=no") `
    -FailureMessage "Failed to read final target project status"
if ($trackedStatusAfter -ne $trackedStatusBefore) {
    throw @"
Tracked project status changed during Harness installation.
Before:
$trackedStatusBefore
After:
$trackedStatusAfter
"@
}

Write-Host ""
Write-Host "Harness installation or upgrade passed."
Write-Host "Project: $ProjectRoot"
Write-Host "Version: $installedVersion"
Write-Host "Installed runtime: $Runtime"
Write-Host ""
Write-Host "Current project status:"
Invoke-NativeCommand `
    -FilePath "git" `
    -Arguments @("-C", $ProjectRoot, "status", "--short") `
    -FailureMessage "Failed to print final project status"
Write-Host ""
Write-Host "Close existing Codex sessions and start a new session from:"
Write-Host $ProjectRoot
