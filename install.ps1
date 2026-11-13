param(
    [switch]$ResearchOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($env:OS -ne 'Windows_NT') {
    throw 'This installer requires Windows because the active dashboard uses MetaTrader 5.'
}

$projectRoot = $PSScriptRoot
$migration = Join-Path $projectRoot 'finish-layout.ps1'
if (Test-Path -LiteralPath $migration) { & $migration }
$libDir = Join-Path $projectRoot 'lib'
New-Item -ItemType Directory -Path $libDir -Force | Out-Null
$venvDir = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$probe = 'import sys; print(sys.version_info.major, sys.version_info.minor, 64 if sys.maxsize > 2**32 else 32, sys.executable, sep=chr(124))'

function Get-CompatiblePython {
    param([string]$Command, [string[]]$Prefix = @())

    try {
        $output = & $Command @Prefix -c $probe 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $output) { return $null }
        $parts = ($output | Select-Object -Last 1) -split '\|', 4
        if ($parts.Count -ne 4 -or $parts[2] -ne '64') { return $null }
        $version = $parts[0] + '.' + $parts[1]
        if ($version -notin @('3.11', '3.12', '3.13', '3.14')) { return $null }
        return @{ Version = $version; Path = $parts[3] }
    } catch {
        return $null
    }
}

function Invoke-ProjectPython {
    param([string[]]$PythonArgs)
    & $venvPython @PythonArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed (exit code $LASTEXITCODE): $($PythonArgs -join ' ')"
    }
}

$existing = $null
if (Test-Path -LiteralPath $venvPython) {
    $existing = Get-CompatiblePython -Command $venvPython
}

if (-not $existing) {
    $selected = $null
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($version in @('3.11', '3.12', '3.13', '3.14')) {
            $selected = Get-CompatiblePython -Command 'py' -Prefix @("-$version")
            if ($selected) { break }
        }
    }
    if (-not $selected) {
        foreach ($command in @('python', 'python3')) {
            if (Get-Command $command -ErrorAction SilentlyContinue) {
                $selected = Get-CompatiblePython -Command $command
                if ($selected) { break }
            }
        }
    }
    if (-not $selected) {
        throw 'Install 64-bit Python 3.11–3.14 from https://www.python.org/downloads/windows/ and rerun .\install.cmd. Python 3.15 is not supported by the MetaTrader5 package.'
    }

    if (Test-Path -LiteralPath $venvDir) {
        $expected = [IO.Path]::GetFullPath((Join-Path $projectRoot '.venv'))
        $actual = [IO.Path]::GetFullPath($venvDir)
        if ($actual -ne $expected) { throw 'Refusing to move an unexpected virtual environment path.' }
        $backup = Join-Path $libDir ('.venv-old-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 6))
        $rootPrefix = [IO.Path]::GetFullPath($projectRoot).TrimEnd('\') + '\'
        if (-not [IO.Path]::GetFullPath($backup).StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Refusing to move the virtual environment outside the project.'
        }
        Write-Host "Moving incompatible environment to $backup"
        try {
            Move-Item -LiteralPath $venvDir -Destination $backup
        } catch {
            throw 'Could not replace .venv. Close the dashboard and worker, then rerun .\install.cmd. The old environment was left intact.'
        }
    }
    Write-Host "Creating .venv with Python $($selected.Version)..."
    & $selected.Path -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}

Push-Location $projectRoot
try {
    Write-Host 'Installing Python dependencies...'
    $requirements = @('-m', 'pip', 'install', '-r', 'requirements.txt')
    if (-not $ResearchOnly) { $requirements += @('-r', 'requirements-mt5.txt') }
    Invoke-ProjectPython -PythonArgs $requirements
    Invoke-ProjectPython -PythonArgs @('src/main/code/register_source.py')

    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.env'))) {
        Copy-Item -LiteralPath (Join-Path $projectRoot '.env.example') -Destination (Join-Path $projectRoot '.env')
        Write-Host 'Created .env from .env.example. Configure your news provider before trading.'
    } else {
        Write-Host 'Keeping existing .env.'
    }

    if ($ResearchOnly) {
        Invoke-ProjectPython -PythonArgs @('-c', 'import streamlit')
    } else {
        Invoke-ProjectPython -PythonArgs @('-c', 'import MetaTrader5, streamlit')
    }
    Write-Host 'Installation complete. Start the dashboard with .\run.cmd.'
} finally {
    Pop-Location
}
