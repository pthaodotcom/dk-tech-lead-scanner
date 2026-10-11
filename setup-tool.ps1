param(
  [switch]$SkipModelWarmup,
  [switch]$SkipShortcuts
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'

try {
  Push-Location $root
  if (-not (Test-Path -LiteralPath $python)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $launcher) { throw 'Install Python 3.13 (64-bit) with its launcher, then run setup-tool.cmd again. See README.md.' }
    & $launcher.Source -3.13 -m venv (Join-Path $root '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create the Python 3.13 environment. Install Python 3.13 (64-bit), then retry.' }
  }

  & $python -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 13) and sys.maxsize > 2**32 else 1)'
  if ($LASTEXITCODE -ne 0) { throw 'This .venv must use Python 3.13 (64-bit). Rename the existing .venv folder, then retry setup.' }
  Write-Host '[1/4] Installing Python dependencies...'
  & $python -m pip install -q -r (Join-Path $root 'requirements.txt')
  if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the pip error and Internet access.' }

  Write-Host '[2/4] Preparing Ollama and Qwen3 1.7B...'
  $ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
  $ollama = if ($ollamaCommand) { $ollamaCommand.Source } else { $null }
  foreach ($candidate in @("$env:LOCALAPPDATA\Programs\Ollama\ollama.exe", 'C:\Program Files\Ollama\ollama.exe')) {
    if (-not $ollama -and (Test-Path -LiteralPath $candidate)) { $ollama = $candidate }
  }
  if (-not $ollama) { throw 'Install Ollama from https://ollama.com/download/windows, then run setup-tool.cmd again.' }
  $tags = $null
  try { $tags = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 } catch {}
  if (-not $tags) {
    Start-Process -FilePath $ollama -ArgumentList @('serve') -WindowStyle Hidden
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
      Start-Sleep -Milliseconds 500
      try { $tags = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2; break } catch {}
    }
  }
  if (-not $tags) { throw 'Ollama did not start on port 11434.' }
  if (-not ($tags.models.name -contains 'qwen3:1.7b')) {
    & $ollama pull 'qwen3:1.7b'
    if ($LASTEXITCODE -ne 0) { throw 'Cannot download qwen3:1.7b. Check Internet access, then retry.' }
  }

  Write-Host '[3/4] Preparing Laya multilingual (uses the local cache when available)...'
  if (-not $SkipModelWarmup) {
    $env:USE_TF = '0'
    & $python (Join-Path $root 'scripts\warmup-laya.py')
    if ($LASTEXITCODE -ne 0) { throw 'Laya preparation failed. Check Hugging Face access, then retry.' }
  }

  Write-Host '[4/4] Creating shortcuts...'
  if (-not $SkipShortcuts) { & (Join-Path $root 'create-shortcut.ps1') }
  Write-Host 'Setup complete. Run start-tool.cmd, then follow the Chrome extension steps in README.md.'
} catch {
  Write-Host ('Setup failed: ' + $_.Exception.Message) -ForegroundColor Red
  exit 1
} finally {
  Pop-Location
}
