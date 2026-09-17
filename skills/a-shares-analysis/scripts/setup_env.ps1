# setup_env.ps1 — zero-dependency environment bootstrap for a-shares-analysis
#
# Runs with ONLY what Windows ships (PowerShell 5.1+). The AI agent invokes it;
# the end user types nothing and installs nothing.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_env.ps1 [-CheckOnly]
#
# Resolution order (most-likely-first — typical machines already have Python;
# uv is the FALLBACK, not the default):
#   1. existing .venv usable?                                    -> done
#   2. system python: py -3 / python / python3 (real install,
#      >= 3.9; Microsoft Store stub is detected and rejected)    -> setup_env.py
#   3. uv already present (PATH / ~/.local/bin / winget Links)   -> uv venv
#   4. no python, no uv? auto-install uv (winget, else official
#      irm script; per-user, no admin) -> uv-managed CPython     -> uv venv
#   5. deps via pandas/numpy/pytest with PyPI -> Tsinghua -> Aliyun fallback
# Output: single-line JSON on stdout (same emit contract as the Python CLIs).

param([switch]$CheckOnly)
$ErrorActionPreference = 'Continue'

$SkillDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$VenvDir  = Join-Path $SkillDir '.venv'
$VenvPy   = Join-Path $VenvDir 'Scripts\python.exe'
$SetupPy  = Join-Path $SkillDir 'scripts\setup_env.py'

function Emit($obj) { $obj | ConvertTo-Json -Compress -Depth 4 | Write-Output }

function Test-Venv {
    if (-not (Test-Path $VenvPy)) { return $false }
    & $VenvPy -c "import pandas, numpy" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

# Real, usable system python (>= 3.9). Rejects the Microsoft Store stub
# (prints nothing, exits non-zero) and ancient versions.
function Find-SystemPython {
    $candidates = @()
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { $candidates += ,@($py.Source, '-3') }
    foreach ($name in @('python', 'python3')) {
        $c = Get-Command $name -ErrorAction SilentlyContinue
        if ($c) { $candidates += ,@($c.Source) }
    }
    foreach ($cmd in $candidates) {
        $exe = $cmd[0]
        $extra = if ($cmd.Count -gt 1) { $cmd[1] } else { $null }
        $argv = @(); if ($extra) { $argv += $extra }
        $out = & $exe @argv --version 2>$null
        if ($LASTEXITCODE -ne 0) { continue }                 # stub / broken
        $ver = "$out".Trim()
        if ($ver -notmatch 'Python 3\.(\d+)') { continue }    # stub prints nothing
        if ([int]$Matches[1] -lt 9) { continue }              # too old
        return @{ exe = $exe; args = $argv; version = $ver }
    }
    return $null
}

# ---------------------------------------------------------------- 1. existing venv
if (Test-Venv) {
    Emit @{ status = 'ok'; detail = 'venv ready'; venv_python = $VenvPy; route = 'existing-venv' }
    exit 0
}
if ($CheckOnly) {
    Emit @{ status = 'incomplete'; detail = '.venv missing or lacks pandas/numpy'; venv_python = $null; route = 'bootstrap-needed' }
    exit 1
}

# ---------------------------------------------------------------- 2. system python first
$sysPy = Find-SystemPython
if ($sysPy) {
    Write-Host ("[setup_env] using system python: {0} ({1})" -f $sysPy.exe, $sysPy.version)
    & $sysPy.exe @($sysPy.args + $SetupPy) 2>$null | Out-Null
    if (Test-Venv) {
        Emit @{ status = 'ok'; detail = "venv ready via system python ($($sysPy.version))"; venv_python = $VenvPy; route = 'system-python' }
        exit 0
    }
    Write-Host '[setup_env] system python route failed (venv/pip); falling back to uv'
}

# ---------------------------------------------------------------- 3. locate existing uv
$uvPaths = @(
    (Get-Command uv -ErrorAction SilentlyContinue).Source,
    (Join-Path $env:USERPROFILE '.local\bin\uv.exe'),
    (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\uv.exe')
) | Where-Object { $_ -and (Test-Path $_) }
$uv = $uvPaths | Select-Object -First 1
$installedUv = $false

# ---------------------------------------------------------------- 4. install uv only as last resort
if (-not $uv) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host '[setup_env] no usable python; installing uv via winget (per-user, no admin)...'
        & winget install -e --id Astral-Sh.UV --silent `
            --accept-source-agreements --accept-package-agreements 2>$null | Out-Null
        $cand = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\uv.exe'
        if (Test-Path $cand) { $uv = $cand; $installedUv = $true }
    }
    if (-not $uv) {
        Write-Host '[setup_env] winget unavailable/failed; using official uv installer (irm)...'
        & powershell -NoProfile -ExecutionPolicy ByPass -Command `
            "irm https://astral.sh/uv/install.ps1 | iex" 2>$null | Out-Null
        $cand = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
        if (Test-Path $cand) { $uv = $cand; $installedUv = $true }
    }
}
if (-not $uv) {
    Emit @{ status = 'failed'; detail = 'no usable python, and uv install failed (network?)'; venv_python = $null; route = 'none' }
    exit 1
}
Write-Host "[setup_env] using uv: $uv"

# ---------------------------------------------------------------- 5. uv venv (+ managed CPython) + deps
if (Test-Path $VenvDir) { Remove-Item -Recurse -Force $VenvDir -ErrorAction SilentlyContinue }
& $uv venv $VenvDir --python 3.12 2>$null | Out-Null
if (-not (Test-Path $VenvPy)) {
    Emit @{ status = 'failed'; detail = 'uv venv failed (needs network to download CPython 3.12)'; venv_python = $null; route = 'uv'; installed_uv = $installedUv }
    exit 1
}

$mirrors = @($null, 'https://pypi.tuna.tsinghua.edu.cn/simple', 'https://mirrors.aliyun.com/pypi/simple')
foreach ($m in $mirrors) {
    $args = @('pip', 'install', '--python', $VenvPy, 'pandas', 'numpy', 'pytest')
    if ($m) { $args += @('--index-url', $m) }
    Write-Host ("[setup_env] uv pip install from {0}..." -f ($(if ($m) { $m } else { 'PyPI' })))
    & $uv @args 2>$null | Out-Null
    if (Test-Venv) {
        Emit @{ status = 'ok'; detail = 'venv ready via uv fallback'; venv_python = $VenvPy; route = 'uv-fallback'; installed_uv = $installedUv }
        exit 0
    }
}
Emit @{ status = 'failed'; detail = 'dependency install failed on all mirrors'; venv_python = $VenvPy; route = 'uv-fallback'; installed_uv = $installedUv }
exit 1
