param(
    [switch]$Check
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = $PSScriptRoot
$migration = Join-Path $projectRoot 'finish-layout.ps1'
if (Test-Path -LiteralPath $migration) { & $migration }
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$install = Join-Path $projectRoot 'install.ps1'
$needsInstall = -not (Test-Path -LiteralPath $python)

if (-not $needsInstall) {
    & $python -c 'import MetaTrader5, streamlit, scalp_lab, scalp_lab_exness' 2>$null
    $needsInstall = $LASTEXITCODE -ne 0
}
if ($needsInstall) {
    Write-Host 'Preparing the Python environment...'
    & $install
    if (-not (Test-Path -LiteralPath $python)) { throw 'Installation did not create .venv.' }
}

$envFile = Join-Path $projectRoot '.env'
if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $projectRoot '.env.example') -Destination $envFile
    Write-Host 'Created .env from .env.example. Configure your news provider before trading.'
}
if (Test-Path -LiteralPath $envFile) {
    $providerLines = Get-Content -LiteralPath $envFile | Where-Object { $_ -match '^\s*(IC_MARKETS|EXNESS)_NEWS_PROVIDER\s*=' }
    if ($providerLines | Where-Object { ($_ -split '=', 2)[1].Trim() -eq 'ollama' }) {
        $ollamaReady = $false
        try {
            $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2
            $ollamaReady = $true
        } catch { }
        if (-not $ollamaReady) {
            $ollama = Get-Command ollama -ErrorAction SilentlyContinue
            $ollamaPath = if ($ollama) { $ollama.Source } else { Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe' }
            if (Test-Path -LiteralPath $ollamaPath) {
                try {
                    Start-Process -FilePath $ollamaPath -ArgumentList 'serve' -WindowStyle Hidden
                    for ($attempt = 0; $attempt -lt 10; $attempt++) {
                        Start-Sleep -Seconds 1
                        try {
                            $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2
                            $ollamaReady = $true
                            break
                        } catch { }
                    }
                } catch { Write-Warning "Could not start Ollama: $($_.Exception.Message)" }
            }
        }
        if (-not $ollamaReady) { Write-Warning 'Ollama is unavailable. The dashboard can open, but news-gated entries will remain blocked.' }
    }
}

if (-not (Get-Process terminal64 -ErrorAction SilentlyContinue)) {
    Write-Warning 'No MT5 terminal is open. Sign in to the selected broker account before connecting in the dashboard.'
}

if ($Check) {
    Write-Host 'Preflight complete. The dashboard was not launched.'
    return
}

Push-Location $projectRoot
try {
    Write-Host 'Opening the local gold dashboard. Press Ctrl+C here to stop it.'
    & $python -m streamlit run (Join-Path $projectRoot 'src\main\code\dashboard.py') --server.address 127.0.0.1
    if ($LASTEXITCODE -ne 0) { throw "Dashboard exited with code $LASTEXITCODE." }
} finally {
    Pop-Location
}
