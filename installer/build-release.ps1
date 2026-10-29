[CmdletBinding()]
param(
    [string]$InnoCompiler
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$version = '1.3'
$tag = "v$version"
$repoRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $PSScriptRoot 'HANDMOVE.iss'
$outputDirectory = Join-Path $repoRoot 'dist'
$repositoryArchive = Join-Path $outputDirectory "HANDMOVE-Repository-v$version.zip"

Push-Location $repoRoot
try {
    $workingChanges = & git status --porcelain
    if ($workingChanges) {
        throw 'Build the release installer from a clean checkout.'
    }

    $headCommit = (& git rev-parse HEAD).Trim()
    $tagCommit = (& git rev-parse --verify "refs/tags/$tag^{commit}").Trim()
    if ($LASTEXITCODE -ne 0 -or $headCommit -ne $tagCommit) {
        throw "Check out the commit tagged $tag before building the release installer."
    }

    $compilerPath = $null
    if ($InnoCompiler) {
        $compilerPath = (Resolve-Path -LiteralPath $InnoCompiler).Path
    } else {
        $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if ($command) {
            $compilerPath = $command.Source
        } else {
            $programFiles = [Environment]::GetEnvironmentVariable('ProgramFiles')
            $programFilesX86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
            $candidates = @(
                (Join-Path $programFiles 'Inno Setup 7\ISCC.exe'),
                (Join-Path $programFilesX86 'Inno Setup 7\ISCC.exe'),
                (Join-Path $programFiles 'Inno Setup 6\ISCC.exe'),
                (Join-Path $programFilesX86 'Inno Setup 6\ISCC.exe')
            )
            $compilerPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        }
    }

    if (-not $compilerPath -or -not (Test-Path -LiteralPath $compilerPath)) {
        throw 'ISCC.exe was not found. Install Inno Setup or pass its path with -InnoCompiler.'
    }

    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
    & git archive --format=zip "--output=$repositoryArchive" HEAD
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not create the HANDMOVE repository archive.'
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($repositoryArchive)
    try {
        $expandedSize = [long](($zip.Entries | Measure-Object -Property Length -Sum).Sum)
    } finally {
        $zip.Dispose()
    }

    $archiveHash = (Get-FileHash -LiteralPath $repositoryArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    $hashArgument = "/DRepositoryArchiveHash=$archiveHash"
    $sizeArgument = "/DRepositoryArchiveExpandedSize=$expandedSize"
    & $compilerPath $hashArgument $sizeArgument $scriptPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Inno Setup failed to compile HANDMOVE.iss.'
    }

    Write-Output "Repository archive: $repositoryArchive"
    Write-Output "Expanded size: $expandedSize bytes"
    Write-Output "SHA-256: $archiveHash"
    Write-Output "Installer: $(Join-Path $outputDirectory "HANDMOVE-Setup-v$version.exe")"
} finally {
    Pop-Location
}
