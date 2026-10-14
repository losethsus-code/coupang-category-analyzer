param([switch]$Enable,[switch]$Disable)
$ErrorActionPreference='Stop'
$startup = [Environment]::GetFolderPath('Startup')
$link = Join-Path $startup 'Coupang_Sourcing_Explorer.lnk'
if ($Disable) {
  Remove-Item -Force -ErrorAction SilentlyContinue $link
  Write-Host 'Removed Windows logon autostart.'
  exit
}
if ($Enable) {
  $target = Join-Path $PSScriptRoot 'START.bat'
  $shell = New-Object -ComObject WScript.Shell
  $shortcut=$shell.CreateShortcut($link)
  $shortcut.TargetPath=$target
  $shortcut.WorkingDirectory=$PSScriptRoot
  $shortcut.Description='Start Coupang Sourcing Explorer on logon'
  $shortcut.Save()
  Write-Host ('Windows logon autostart enabled: ' + $link)
  exit
}
Write-Host 'Specify -Enable or -Disable.'
