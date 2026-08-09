<#
.SYNOPSIS
  Install the claude-video-parser skill for Claude Code on Windows.

.EXAMPLE
  .\scripts\install.ps1              # install to $HOME\.claude\skills (all projects)
  .\scripts\install.ps1 -Project     # install to .\.claude\skills (this repo only)
  .\scripts\install.ps1 -Force       # overwrite an existing install
#>
[CmdletBinding()]
param(
    [switch]$Project,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$skillSrc = Join-Path $repoRoot 'skills\claude-video-parser'

if (-not (Test-Path $skillSrc)) {
    Write-Error "Skill source not found at $skillSrc"
}

$targetRoot = if ($Project) {
    Join-Path (Get-Location) '.claude\skills'
} else {
    Join-Path $HOME '.claude\skills'
}
$target = Join-Path $targetRoot 'claude-video-parser'

if ((Test-Path $target) -and -not $Force) {
    Write-Host "Already installed at $target" -ForegroundColor Yellow
    Write-Host "Re-run with -Force to overwrite." -ForegroundColor Yellow
    exit 1
}

New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
if (Test-Path $target) { Remove-Item -Recurse -Force $target }
Copy-Item -Recurse -Force $skillSrc $target

Write-Host "Installed -> $target" -ForegroundColor Green

# --- dependency check ------------------------------------------------------
$missing = @()
foreach ($bin in 'ffmpeg', 'ffprobe') {
    if (-not (Get-Command $bin -ErrorAction SilentlyContinue)) { $missing += $bin }
}
if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "Missing on PATH: $($missing -join ', ')" -ForegroundColor Red
    Write-Host "  winget install Gyan.FFmpeg" -ForegroundColor Red
    Write-Host "  (then open a new terminal so PATH refreshes)" -ForegroundColor Red
} else {
    Write-Host "ffmpeg + ffprobe found" -ForegroundColor Green
}

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) {
    Write-Host "python not found on PATH" -ForegroundColor Red
} else {
    $v = & $py.Source --version
    Write-Host "$v found" -ForegroundColor Green
}

Write-Host ""
Write-Host "Restart Claude Code, then try:" -ForegroundColor Cyan
Write-Host '  "QA sent me this recording of checkout breaking - .\bug.mp4"'
