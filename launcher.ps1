# Coupang Sourcing Explorer Windows launcher - v0.2
# Designed for Windows PowerShell 5.1: native stderr is NOT allowed to abort setup.
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$logdir = Join-Path $root 'logs'
$datadir = Join-Path $root 'app_data'
New-Item -ItemType Directory -Force -Path $logdir, $datadir | Out-Null
$log = Join-Path $logdir 'launcher.log'
$stderr = Join-Path $logdir 'streamlit_stderr.log'
$stdout = Join-Path $logdir 'streamlit_stdout.log'
$setupOut = Join-Path $logdir 'setup_stdout.log'
$setupErr = Join-Path $logdir 'setup_stderr.log'
$python = Join-Path $root '.venv\Scripts\python.exe'
$venvPath = Join-Path $root '.venv'
$url = 'http://127.0.0.1:8789'
$pidFile = Join-Path $datadir 'server.pid'

function Note([string]$value) {
  $line = ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $value)
  Write-Host $line
  Add-Content -LiteralPath $log -Value $line -Encoding UTF8
}
function Healthy {
  try {
    $response = Invoke-WebRequest -Uri ($url + '/_stcore/health') -UseBasicParsing -TimeoutSec 2
    return $response.StatusCode -eq 200
  } catch { return $false }
}
function Show-LogTail([string]$path, [int]$lines=16) {
  if (Test-Path -LiteralPath $path) {
    Write-Host ('--- ' + $path + ' (last lines) ---') -ForegroundColor Yellow
    Get-Content -LiteralPath $path -Tail $lines -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
  }
}
# Powershell 5.1 can throw NativeCommandError when a native process writes to stderr,
# even if a nonzero exit status is expected (e.g., checking missing libraries).
# Start-Process with redirected output avoids this trap.
function Run-Native([string]$exe, [string]$arguments, [string]$label) {
  Remove-Item -LiteralPath $setupOut,$setupErr -Force -ErrorAction SilentlyContinue
  Note ($label + ': ' + $exe + ' ' + $arguments)
  $p = Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $root -RedirectStandardOutput $setupOut -RedirectStandardError $setupErr -PassThru -Wait
  $code = [int]$p.ExitCode
  Note ($label + ' exit code: ' + $code)
  if ($code -ne 0) {
    Show-LogTail $setupErr 15
    Show-LogTail $setupOut 5
  }
  return $code
}

try {
  Note 'Sourcing Explorer v0.6 launcher started.'
  if (Healthy) {
    if (!(Test-Path -LiteralPath $pidFile)) {
      throw 'Port 8789 is already running another Streamlit process. Close the old explorer and run START.bat again.'
    }
    $savedPid=[int](Get-Content -LiteralPath $pidFile -TotalCount 1)
    $running=Get-Process -Id $savedPid -ErrorAction SilentlyContinue
    if (!$running) {
      throw 'Port 8789 is occupied, but our recorded process is not running. Close the old explorer and run START.bat again.'
    }
    Note 'Server already running. Opening browser.'
    Start-Process $url
    exit 0
  }

  if (!(Test-Path -LiteralPath $python)) {
    Note 'Creating isolated Python environment.'
    $found = $false
    $py = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($py) {
      $code = Run-Native $py.Source ('-3 -m venv "' + $venvPath + '"') 'Create venv with py -3'
      if ($code -eq 0 -and (Test-Path -LiteralPath $python)) { $found = $true }
    }
    if (!$found) {
      $plain = Get-Command 'python.exe' -ErrorAction SilentlyContinue
      if (!$plain) { throw 'Python not found. Install Python 3.10-3.13 and enable Add python.exe to PATH.' }
      $code = Run-Native $plain.Source ('-m venv "' + $venvPath + '"') 'Create venv with python'
      if ($code -ne 0 -or !(Test-Path -LiteralPath $python)) {
        throw 'Unable to create Python environment. Check logs/setup_stderr.log.'
      }
    }
  }

  # Missing packages are NORMAL on first run. Do not treat Python traceback as launcher crash.
  $check = Run-Native $python '-c "import streamlit, pandas, openpyxl"' 'Check dependencies'
  if ($check -ne 0) {
    Note 'Installing first-run dependencies. Internet connection is needed.'
    $install = Run-Native $python '-m pip install --disable-pip-version-check -r requirements.txt' 'Install dependencies'
    if ($install -ne 0) { throw 'Package installation failed. Check logs/setup_stderr.log and setup_stdout.log.' }
    $check = Run-Native $python '-c "import streamlit, pandas, openpyxl"' 'Verify dependencies'
    if ($check -ne 0) { throw 'Packages installed but Python cannot import them. Check setup_stderr.log.' }
  }

  Note 'Starting Streamlit at http://127.0.0.1:8789.'
  Remove-Item -LiteralPath $stderr,$stdout -Force -ErrorAction SilentlyContinue
  $proc = Start-Process -FilePath $python -ArgumentList '-m streamlit run app.py --server.address 127.0.0.1 --server.port 8789 --server.headless true --server.fileWatcherType none --browser.gatherUsageStats false' -WorkingDirectory $root -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
  for ($i=0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if (Healthy) {
      Set-Content -LiteralPath $pidFile -Value $proc.Id -Encoding ASCII
      Note ('Server ready. PID=' + $proc.Id)
      Start-Process $url
      exit 0
    }
    if ($proc.HasExited) { break }
  }
  Show-LogTail $stderr 20
  Show-LogTail $stdout 10
  throw 'Streamlit did not start. Check logs/streamlit_stderr.log.'
}
catch {
  Note ('ERROR: ' + $_.Exception.Message)
  Write-Host 'Open the logs folder or send its files for diagnosis.' -ForegroundColor Red
  Write-Host ('Log folder: ' + $logdir)
  exit 1
}
