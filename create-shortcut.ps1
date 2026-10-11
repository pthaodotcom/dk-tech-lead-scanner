$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('Desktop')

$wsh = New-Object -ComObject WScript.Shell
$vbsPath = Join-Path $root 'start-tool.vbs'
$cmdPath = Join-Path $root 'start-tool.cmd'

# Tim duong dan Chrome de lay icon
$chromeCandidates = @(
  'C:\Program Files\Google\Chrome\Application\chrome.exe',
  "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
  'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'
)
$iconPath = 'shell32.dll,220'
foreach ($candidate in $chromeCandidates) {
  if (Test-Path -LiteralPath $candidate) {
    $iconPath = "$candidate,0"
    break
  }
}

$shortcuts = @(
  (Join-Path $desktop 'DK Tech Lead Scanner.lnk'),
  (Join-Path $root 'DK Tech Lead Scanner.lnk')
)

foreach ($scPath in $shortcuts) {
  $shortcut = $wsh.CreateShortcut($scPath)
  $shortcut.TargetPath = 'wscript.exe'
  $shortcut.Arguments = "`"$vbsPath`""
  $shortcut.WorkingDirectory = $root
  $shortcut.IconLocation = $iconPath
  $shortcut.Description = 'Khoi dong DK Tech Lead Scanner (Ollama + Backend + Dashboard)'
  $shortcut.Save()
  Write-Host "Da tao shortcut: $scPath"
}
