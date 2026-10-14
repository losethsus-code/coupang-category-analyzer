# Coupang Sourcing Explorer: install complete, verified source release from GitHub.
# Safe for Windows PowerShell 5.1. User data and virtualenv are never replaced.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = $PSScriptRoot
$repository = 'losethsus-code/coupang-category-analyzer'
$archiveUrl = 'https://github.com/' + $repository + '/archive/refs/heads/main.zip'
$runStamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$work = Join-Path $env:TEMP ('coupang_sourcing_update_' + $runStamp)
$backups = Join-Path $root ('app_data\code_backups\' + $runStamp)
$zipfile = Join-Path $work 'latest.zip'
$unpacked = Join-Path $work 'unpacked'
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $work,$unpacked,$logDir | Out-Null
$logFile = Join-Path $logDir 'github_update.log'
function Log([string]$value) {
  $line = ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $value)
  Write-Host $line
  Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
}
function Find-Server {
  $pidPath = Join-Path $root 'app_data\server.pid'
  if (!(Test-Path -LiteralPath $pidPath)) { return $null }
  try { $serverId = [int](Get-Content -LiteralPath $pidPath -TotalCount 1) } catch { return $null }
  $p = Get-CimInstance Win32_Process -Filter "ProcessId=$serverId" -ErrorAction SilentlyContinue
  if ($p -and $p.CommandLine -and $p.CommandLine -match 'streamlit' -and $p.CommandLine -match 'app\.py' -and $p.CommandLine -match '8789') { return $p }
  return $null
}
try {
  Log 'Starting verified GitHub update.'
  $oldServer=Find-Server
  if ($oldServer) {
    Log ('Stopping this application server, PID ' + $oldServer.ProcessId)
    Stop-Process -Id $oldServer.ProcessId -Force -ErrorAction Stop
    Start-Sleep -Seconds 2
  }
  Log ('Downloading: ' + $archiveUrl)
  Invoke-WebRequest -Uri $archiveUrl -OutFile $zipfile -UseBasicParsing -TimeoutSec 120
  Expand-Archive -LiteralPath $zipfile -DestinationPath $unpacked -Force
  $source = @(Get-ChildItem -LiteralPath $unpacked -Directory) | Select-Object -First 1
  if (!$source) { throw 'GitHub archive has no source folder.' }
  $src = $source.FullName
  $manifestFile = Join-Path $src 'release_manifest.json'
  if (!(Test-Path -LiteralPath $manifestFile)) { throw 'No release manifest. No files were replaced.' }
  $manifest = Get-Content -LiteralPath $manifestFile -Raw -Encoding UTF8 | ConvertFrom-Json
  if (!$manifest.files -or !$manifest.version) { throw 'Invalid release manifest.' }
  $entries = @($manifest.files.PSObject.Properties)
  if ($entries.Count -lt 10) { throw 'Incomplete GitHub release. No files were replaced.' }
  foreach ($entry in $entries) {
    $rel = $entry.Name
    if ($rel -match '^/' -or $rel -match '\.\.' -or $rel -match '^[A-Za-z]:') { throw ('Unsafe filename in manifest: ' + $rel) }
    if ($rel -like 'app_data/*' -or $rel -like '.venv/*' -or $rel -like 'logs/*') { throw ('Protected path in manifest: ' + $rel) }
    $f = Join-Path $src $rel
    if (!(Test-Path -LiteralPath $f -PathType Leaf)) { throw ('Missing release file: ' + $rel) }
    $hash = (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne ([string]$entry.Value).ToLowerInvariant()) { throw ('Checksum mismatch: ' + $rel) }
  }
  Log ('Verified source release version ' + $manifest.version + '; ' + $entries.Count + ' files.')
  # Syntax check before writing anything. Use venv Python when available.
  $python = Join-Path $root '.venv\Scripts\python.exe'
  if (!(Test-Path -LiteralPath $python)) {
    $found = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($found) { $python = $found.Source }
    else { $found = Get-Command 'python.exe' -ErrorAction SilentlyContinue; if ($found) { $python = $found.Source } else { $python = '' } }
  }
  if ($python) {
    $codeFiles = @('app.py','core.py','coupang_api.py','search_1p.py','launcher.ps1')
    foreach ($file in $codeFiles) { if (!(Test-Path -LiteralPath (Join-Path $src $file))) { throw ('Incomplete package: ' + $file) } }
    $pyFiles = @('app.py','core.py','coupang_api.py','search_1p.py')
    foreach ($file in $pyFiles) {
      $candidate=Join-Path $src $file
      # Python AST syntax compile without generating bytecode files.
      $result = & $python -c 'import ast,sys; ast.parse(open(sys.argv[1],encoding="utf-8").read())' $candidate 2>&1
      if ($LASTEXITCODE -ne 0) { throw ('Python syntax check failed for ' + $file + ': ' + ($result | Out-String)) }
    }
  }
  New-Item -ItemType Directory -Force -Path $backups | Out-Null
  $copied=@()
  try {
    foreach ($entry in $entries) {
      $rel=$entry.Name
      $target=Join-Path $root $rel
      $from=Join-Path $src $rel
      if (Test-Path -LiteralPath $target) {
        $old=Join-Path $backups $rel
        $dir=Split-Path -Parent $old
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        Copy-Item -LiteralPath $target -Destination $old -Force
      }
      $targetDir=Split-Path -Parent $target
      New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
      Copy-Item -LiteralPath $from -Destination $target -Force
      $copied+= $rel
    }
    Copy-Item -LiteralPath $manifestFile -Destination (Join-Path $root 'release_manifest.json') -Force
    Log ('Update succeeded. Version: ' + $manifest.version)
  } catch {
    Log ('Update failed while copying, rolling back: ' + $_.Exception.Message)
    foreach ($rel in $copied) {
      $old=Join-Path $backups $rel
      $target=Join-Path $root $rel
      if (Test-Path -LiteralPath $old) { Copy-Item -LiteralPath $old -Destination $target -Force }
      elseif (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Force }
    }
    throw
  }
  Write-Host 'Update complete. app_data and .venv are preserved.' -ForegroundColor Green
  exit 0
} catch {
  Log ('ERROR: ' + $_.Exception.Message)
  Write-Host 'Update was cancelled. Check logs\github_update.log.' -ForegroundColor Red
  exit 1
} finally {
  Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
