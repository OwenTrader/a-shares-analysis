# setup_env.ps1 — zero-dependency environment bootstrap for a-shares-analysis
#
# Runs with ONLY what Windows ships (PowerShell 5.1+). No Python, no uv, no git
# required beforehand. The AI agent invokes it; the end user types nothing.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_env.ps1 [-CheckOnly]
#
# Chain:
#   1. existing .venv usable?                          -> done
#   2. find uv (PATH, %USERPROFILE%\.local\bin, winget Links)
#   3. no uv? auto-install: winget Astral-Sh.UV, else official irm script
#      (both per-user, no admin required)
#   4. uv venv --python 3.12   -> downloads a uv-managed CPython (no system Python needed)
#   5. uv pip install pandas numpy pytest (PyPI -> Tsinghua -> Aliyun fallback)
# Output: single-line JSON on stdout (same emit contract as the Python CLIs).

param([switch]$CheckOnly)
$ErrorActionPreference = 'Continue'
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()

$SkillDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$VenvDir  = Join-Path $SkillDir '.venv'
$VenvPy   = Join-Path $VenvDir 'Scripts\python.exe'

function Emit($obj) { $obj | ConvertTo-Json -Compress -Depth 4 | Write-Output }

function Test-Venv {
    if (-not (Test-Path $VenvPy)) { return $false }
    & $VenvPy -c "import pandas, numpy" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

# ---------------------------------------------------------------- 1. existing venv
if (Test-Venv) {
    Emit @{ status = 'ok'; detail = 'venv ready'; venv_python = $VenvPy; installed_uv = $false }
    exit 0
}
if ($CheckOnly) {
    Emit @{ status = 'incomplete'; detail = '.venv missing or lacks pandas/numpy'; venv_python = $null; installed_uv = $false }
    exit 1
}

# ---------------------------------------------------------------- 2. locate uv
$uvPaths = @(
    (Get-Command uv -ErrorAction SilentlyContinue).Source,
    (Join-Path $env:USERPROFILE '.local\bin\uv.exe'),
    (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\uv.exe')
) | Where-Object { $_ -and (Test-Path $_) }
$uv = $uvPaths | Select-Object -First 1
$installedUv = $false

# ---------------------------------------------------------------- 3. auto-install uv
if (-not $uv) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host '[setup_env] installing uv via winget (per-user, no admin)...'
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
    Emit @{ status = 'failed'; detail = 'could not install uv (no winget, installer unreachable)'; venv_python = $null; installed_uv = $false }
    exit 1
}
Write-Host "[setup_env] using uv: $uv"

# ---------------------------------------------------------------- 4. venv (+ managed CPython)
if (Test-Path $VenvDir) { Remove-Item -Recurse -Force $VenvDir -ErrorAction SilentlyContinue }
& $uv venv $VenvDir --python 3.12 2>$null | Out-Null
if (-not (Test-Path $VenvPy)) {
    Emit @{ status = 'failed'; detail = 'uv venv failed (check network: needs to download CPython 3.12)'; venv_python = $null; installed_uv = $installedUv }
    exit 1
}

# ---------------------------------------------------------------- 5. deps with mirror fallback
$mirrors = @($null, 'https://pypi.tuna.tsinghua.edu.cn/simple', 'https://mirrors.aliyun.com/pypi/simple')
$installed = $false
foreach ($m in $mirrors) {
    $args = @('pip', 'install', '--python', $VenvPy, 'pandas', 'numpy', 'pytest')
    if ($m) { $args += @('--index-url', $m) }
    Write-Host ("[setup_env] uv pip install from {0}..." -f ($(if ($m) { $m } else { 'PyPI' })))
    & $uv @args 2>$null | Out-Null
    if ((Test-Venv)) { $installed = $true; break }
}
if (-not $installed) {
    Emit @{ status = 'failed'; detail = 'dependency install failed on all mirrors'; venv_python = $VenvPy; installed_uv = $installedUv }
    exit 1
}

Emit @{ status = 'ok'; detail = 'venv ready (uv bootstrap)'; venv_python = $VenvPy; installed_uv = $installedUv }
exit 0
