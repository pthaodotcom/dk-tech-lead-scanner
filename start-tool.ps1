try {
  $ErrorActionPreference = 'Stop'
  $root = Split-Path -Parent $MyInvocation.MyCommand.Path
  $health = 'http://127.0.0.1:9350/health'
  $ollamaHealth = 'http://127.0.0.1:11434/api/tags'
  $ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
  $ollama = if ($ollamaCommand) { $ollamaCommand.Source } else { $null }
  foreach ($candidate in @("$env:LOCALAPPDATA\Programs\Ollama\ollama.exe", 'C:\Program Files\Ollama\ollama.exe')) {
    if (-not $ollama -and (Test-Path -LiteralPath $candidate)) { $ollama = $candidate }
  }
  $ollamaReady = $false

  try {
    $models = Invoke-RestMethod -Uri $ollamaHealth -TimeoutSec 2
    $ollamaReady = $true
  } catch {}

  if (-not $ollamaReady) {
    if (-not $ollama) { throw 'Chưa cài Ollama để chạy Qwen3 1.7B.' }
    Start-Process -FilePath $ollama -ArgumentList @('serve') -WindowStyle Hidden
    for ($i = 0; $i -lt 20; $i++) {
      Start-Sleep -Milliseconds 500
      try {
        $models = Invoke-RestMethod -Uri $ollamaHealth -TimeoutSec 1
        $ollamaReady = $true
        break
      } catch {}
    }
  }

  if (-not $ollamaReady) { throw 'Không khởi động được Ollama.' }
  if (-not ($models.models.name -contains 'qwen3:1.7b')) {
    throw 'Chưa có model qwen3:1.7b. Hãy chạy: ollama pull qwen3:1.7b'
  }

  $ready = $false
  try {
    $response = Invoke-RestMethod -Uri $health -TimeoutSec 2
    $ready = $response.status -eq 'ready'
  } catch {}

  if (-not $ready) {
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
      throw 'Chưa có môi trường Python tại .venv.'
    }
    $env:USE_TF = '0'
    Start-Process -FilePath $python -ArgumentList @('app\server.py') -WorkingDirectory $root -WindowStyle Hidden
    for ($i = 0; $i -lt 20; $i++) {
      Start-Sleep -Milliseconds 250
      try {
        $response = Invoke-RestMethod -Uri $health -TimeoutSec 1
        if ($response.status -eq 'ready') { $ready = $true; break }
      } catch {}
    }
  }

  if (-not $ready) { throw 'Không khởi động được DK-Tech Lead Scanner backend.' }

  $chromeCandidates = @(
    'C:\Program Files\Google\Chrome\Application\chrome.exe',
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
    'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'
  )
  $chrome = $null
  foreach ($candidate in $chromeCandidates) {
    if (Test-Path -LiteralPath $candidate) {
      $chrome = $candidate
      break
    }
  }

  if (-not $chrome) { throw 'Không tìm thấy Google Chrome trên máy tính.' }

  Start-Process -FilePath $chrome -ArgumentList @(
    '--profile-directory=Default',
    'http://127.0.0.1:9350/'
  )
} catch {
  $errMsg = $_.Exception.Message
  try {
    $wsh = New-Object -ComObject WScript.Shell
    $wsh.Popup($errMsg, 0, 'DK Tech Lead Scanner - Lỗi khởi động', 16) | Out-Null
  } catch {
    Write-Error $errMsg
  }
  exit 1
}


