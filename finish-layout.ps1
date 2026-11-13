$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$prefix = $root + '\'
$lib = Join-Path $root 'lib'
$archive = Join-Path $lib 'previous_layout'
$moved = $false
function Assert-Local([string]$path) {
    $full = [IO.Path]::GetFullPath($path)
    if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw "Outside project: $full" }
}
function Move-Local([string]$name, [string]$destination) {
    $source = Join-Path $root $name
    if (-not (Test-Path -LiteralPath $source)) { return }
    Assert-Local $source
    Assert-Local $destination
    if (Test-Path -LiteralPath $destination) { throw "Destination exists: $destination" }
    Move-Item -LiteralPath $source -Destination $destination
    $script:moved = $true
}

New-Item -ItemType Directory -Path $lib, $archive -Force | Out-Null

# The legacy worker keeps the old journal and lock open while it monitors exits.
$lock = Join-Path $root 'gold_worker.lock'
if (Test-Path -LiteralPath $lock) {
    $held = $false
    try {
        $stream = [IO.File]::Open($lock, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        $stream.Dispose()
    } catch [IO.IOException] { $held = $true }
    if ($held) {
        $oldPython = Join-Path $root '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $oldPython)) { throw 'Old worker is active; old Python environment is unavailable.' }
        & $oldPython (Join-Path $root 'src\main\code\migration_safety.py')
        if ($LASTEXITCODE -ne 0) { throw 'Keep the old worker running until open positions close, then rerun install.cmd or run.cmd.' }
        $statusPath = Join-Path $root 'gold_worker_status.json'
        if (-not (Test-Path -LiteralPath $statusPath)) { throw 'Worker is active but its status is unavailable.' }
        $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
        $workerProcess = Get-Process -Id ([int]$status.pid) -ErrorAction SilentlyContinue
        if (-not $workerProcess -or $workerProcess.ProcessName -ne 'python') { throw 'Could not identify the old worker process.' }
        Stop-Process -Id $workerProcess.Id -ErrorAction Stop
        Start-Sleep -Seconds 2
        try {
            $stream = [IO.File]::Open($lock, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
            $stream.Dispose()
        } catch { throw 'Old worker lock is still held; migration stopped.' }
    }
}

# Keep the newest active snapshots. Archive any duplicates from the partial move.
$oldEvents = Join-Path $root 'gold_events.sqlite3'
$newEvents = Join-Path $lib 'gold_events.sqlite3'
if ((Test-Path -LiteralPath $oldEvents) -and (Test-Path -LiteralPath $newEvents)) {
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw 'Python is required to merge the event journals.' }
    & $python (Join-Path $root 'src\main\code\merge_legacy_events.py') $newEvents $oldEvents
    if ($LASTEXITCODE -ne 0) { throw 'Could not merge the event journals.' }
    Move-Local 'gold_events.sqlite3' (Join-Path $archive 'gold_events_after_partial_move.sqlite3')
}

foreach ($name in @('scalp_lab', 'tests', 'dashboard.py', 'dashboard_legacy.py')) {
    Move-Local $name (Join-Path $archive $name)
}
foreach ($name in @('.venv-py315', '.runtime_review', '.test_tmp', '__pycache__', 'data', 'demo_data', 'auto_live')) {
    Move-Local $name (Join-Path $lib $name)
}
Get-ChildItem -LiteralPath $root -Force -Directory | Where-Object { $_.Name -like 'results_*' -or $_.Name -like 'live_*' -or $_.Name -like '.venv-*' } | ForEach-Object {
    Move-Local $_.Name (Join-Path $lib $_.Name)
}
Get-ChildItem -LiteralPath $root -Force -File | Where-Object {
    ($_.Extension -in @('.json', '.csv') -and $_.Name -match '^(gold_|xm_auto_demo|demo_orders|telegram_notifications)') -or
    $_.Extension -in @('.sqlite3', '.db', '.log', '.lock')
} | ForEach-Object {
    $target = Join-Path $lib $_.Name
    if (Test-Path -LiteralPath $target) {
        $archived = Join-Path $archive ($_.BaseName + '_before_final_move' + $_.Extension)
        if (Test-Path -LiteralPath $archived) { throw "Archive destination exists: $archived" }
        Assert-Local $target
        Assert-Local $archived
        Move-Item -LiteralPath $target -Destination $archived
    }
    Move-Local $_.Name $target
}
if ($moved) { Write-Host 'Source, tests, and local files are in src/main/code, src/test/code, and lib.' }
