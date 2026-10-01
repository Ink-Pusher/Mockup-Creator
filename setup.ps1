# Ink Pusher catalog tools -- Windows setup
#
# Run from PowerShell with:
#   irm https://raw.githubusercontent.com/Ink-Pusher/Mockup-Creator/main/setup.ps1 | iex
#
# Installs GitHub Desktop and Python (with PATH set correctly -- the
# checkbox people miss is handled here), then the Python packages the
# catalog scripts need. Everything is idempotent: run it twice and the
# second run just confirms what is already there. It ends by printing
# the four steps only a person can do (accounts and secrets).

$ErrorActionPreference = "Stop"

function Step($msg)  { Write-Host ""; Write-Host ("== " + $msg) -ForegroundColor Cyan }
function Ok($msg)    { Write-Host ("   OK  " + $msg) -ForegroundColor Green }
function Skip($msg)  { Write-Host ("   --  " + $msg) -ForegroundColor DarkGray }
function Fail($msg)  {
    Write-Host ""
    Write-Host ("   PROBLEM: " + $msg) -ForegroundColor Red
    Write-Host "   Nothing was broken -- fix the line above and run the installer again,"
    Write-Host "   or fall back to the manual steps in 'Catalog Onboarding - Part 1 (Windows)'."
    exit 1
}

Write-Host ""
Write-Host "Ink Pusher catalog tools -- setup" -ForegroundColor Cyan
Write-Host "This takes about five minutes. You can watch, nothing needs input."

# ---- winget is the Windows package manager; Windows 10/11 ship it ----
Step "Checking for winget (the Windows app installer)"
if (Get-Command winget -ErrorAction SilentlyContinue) {
    Ok "winget is available"
} else {
    Fail "winget is missing. Install 'App Installer' from the Microsoft Store, then run this again."
}

# ---- GitHub Desktop ----
Step "GitHub Desktop"
$ghd = Join-Path $env:LOCALAPPDATA "GitHubDesktop\GitHubDesktop.exe"
if (Test-Path $ghd) {
    Skip "already installed"
} else {
    winget install --id GitHub.GitHubDesktop -e --accept-source-agreements --accept-package-agreements --silent
    if ($LASTEXITCODE -ne 0) { Fail "GitHub Desktop install returned an error (code $LASTEXITCODE)." }
    Ok "installed"
}

# ---- Python (with PATH -- the installer flag replaces the checkbox) ----
Step "Python"
$havePython = $false
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py -and $py.Source -notmatch "WindowsApps") {
    # The WindowsApps 'python' is a Microsoft Store stub, not a real install.
    $v = & python --version 2>&1
    if ($v -match "Python 3\.(\d+)" -and [int]$Matches[1] -ge 9) { $havePython = $true; Skip ("already installed: " + $v) }
}
if (-not $havePython) {
    winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements `
        --override "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0"
    if ($LASTEXITCODE -ne 0) { Fail "Python install returned an error (code $LASTEXITCODE)." }
    # The new PATH exists in the registry but not in THIS window yet -- reload it.
    $env:Path = [Environment]::GetEnvironmentVariable("Path","User") + ";" + [Environment]::GetEnvironmentVariable("Path","Machine")
    Ok "installed (PATH set -- no checkbox to forget)"
}

# ---- The packages the catalog scripts need ----
Step "Python packages (9 of them -- this is the slow part)"
& python -m pip install --quiet --disable-pip-version-check anthropic requests pillow numpy scipy pytoshop psd-tools six cloudscraper pymupdf
if ($LASTEXITCODE -ne 0) { Fail "package install failed -- scroll up for pip's error." }
Ok "all packages installed"

# ---- Hand over the human steps ----
Write-Host ""
Write-Host "Automated part: DONE." -ForegroundColor Green
Write-Host ""
Write-Host "Now finish these 4 steps yourself:" -ForegroundColor Cyan
Write-Host ""
Write-Host "  1. Open GitHub Desktop and sign in."
Write-Host "     (Accept the collaborator invite from Timm in your email first --"
Write-Host "      no GitHub account yet? Create one free at github.com/join.)"
Write-Host ""
Write-Host "  2. In GitHub Desktop: File > Clone Repository > pick Ink-Pusher/Mockup-Creator."
Write-Host "     IMPORTANT: save it somewhere OUTSIDE OneDrive -- C:\GitHub is good."
Write-Host "     (OneDrive syncing fights with Git and corrupts things.)"
Write-Host ""
Write-Host "  3. In GitHub Desktop: Repository > Open in Command Prompt, then run:"
Write-Host "        python build_descriptions.py setkey" -ForegroundColor Yellow
Write-Host "     and paste the API key Timm gives you. (Your paste stays invisible"
Write-Host "     on purpose -- paste, press Enter.)"
Write-Host ""
Write-Host "  4. In that same window, run:"
Write-Host "        python build_descriptions.py doctor" -ForegroundColor Yellow
Write-Host "     When every line says [OK], you're fully set up."
Write-Host ""
