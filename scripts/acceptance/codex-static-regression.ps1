[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ProjectRoot,

    [ValidateNotNullOrEmpty()]
    [string]$PythonCommand = "python",

    [switch]$TrustProject
)

$ErrorActionPreference = "Stop"
$HarnessRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Message (exit code $LASTEXITCODE)"
    }
}

function Invoke-Captured {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )
    $output = & $FilePath @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        $output | ForEach-Object { Write-Host $_ }
        throw "$Message (exit code $LASTEXITCODE)"
    }
    return (($output | ForEach-Object { "$_" }) -join "`n").Trim()
}

$gitRoot = Invoke-Captured `
    -FilePath "git" `
    -Arguments @("-C", $ProjectRoot, "rev-parse", "--show-toplevel") `
    -Message "Target is not a Git worktree"
if ((Resolve-Path -LiteralPath $gitRoot).Path -ne $ProjectRoot) {
    throw "ProjectRoot must be the exact Git worktree root: $gitRoot"
}

$statusBefore = Invoke-Captured `
    -FilePath "git" `
    -Arguments @("-C", $ProjectRoot, "status", "--short", "--untracked-files=no") `
    -Message "Failed to capture initial tracked status"

# unittest discovery imports top-level Harness modules such as install.py.
# Run from the Harness root so this script is independent of the caller's cwd.
Push-Location -LiteralPath $HarnessRoot
try {
    Invoke-Checked `
        -FilePath $PythonCommand `
        -Arguments @("-m", "unittest", "discover", "-s", "tests", "-v") `
        -Message "Harness unit tests failed"
}
finally {
    Pop-Location
}

$install = Join-Path $HarnessRoot "install.py"
$arguments = @($install, "--project", $ProjectRoot, "--reinstall")
if ($TrustProject) {
    $arguments += "--trust-project"
}

Invoke-Checked `
    -FilePath $PythonCommand `
    -Arguments ($arguments + "--dry-run") `
    -Message "Harness install dry-run failed"
Invoke-Checked `
    -FilePath $PythonCommand `
    -Arguments $arguments `
    -Message "Harness install failed"
Invoke-Checked `
    -FilePath $PythonCommand `
    -Arguments @((Join-Path $HarnessRoot "check.py"), "--project", $ProjectRoot) `
    -Message "Harness projection check failed"

$installed = Join-Path $ProjectRoot ".harness\sitter"
Invoke-Checked `
    -FilePath $PythonCommand `
    -Arguments @((Join-Path $installed "runtime\self_check.py"), "--project", $ProjectRoot) `
    -Message "Installed Harness self-check failed"
Invoke-Checked `
    -FilePath $PythonCommand `
    -Arguments @((Join-Path $installed "runtime\work.py"), "--help") `
    -Message "Work CLI discovery failed"
Invoke-Checked `
    -FilePath $PythonCommand `
    -Arguments @((Join-Path $installed "runtime\delegation_runtime.py"), "--help") `
    -Message "Codex delegation runtime discovery failed"

$statusAfter = Invoke-Captured `
    -FilePath "git" `
    -Arguments @("-C", $ProjectRoot, "status", "--short", "--untracked-files=no") `
    -Message "Failed to capture final tracked status"
if ($statusAfter -ne $statusBefore) {
    throw "Tracked project status changed during V5-A static regression.`nBefore:`n$statusBefore`nAfter:`n$statusAfter"
}

Write-Host "V5-A Codex static regression passed."
Write-Host "Harness: $HarnessRoot"
Write-Host "Project: $ProjectRoot"
