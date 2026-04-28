$ErrorActionPreference = "Stop"

$envFile = Join-Path $PSScriptRoot "..\.env.local"
if (-not (Test-Path $envFile)) {
  throw "No existe .env.local en la raíz del proyecto"
}

Get-Content $envFile | ForEach-Object {
  $line = $_.Trim()
  if (-not $line -or $line.StartsWith("#")) { return }
  $parts = $line.Split("=", 2)
  if ($parts.Count -ne 2) { return }
  [System.Environment]::SetEnvironmentVariable($parts[0], $parts[1], "Process")
}

$hostAddr = if ($env:PR_REVISOR_HOST) { $env:PR_REVISOR_HOST } else { "127.0.0.1" }
$port = if ($env:PR_REVISOR_PORT) { $env:PR_REVISOR_PORT } else { "8001" }
$url = "http://${hostAddr}:$port"

Write-Host "Iniciando pr-revisor en $url" -ForegroundColor Cyan
python -m uvicorn service.app:app --host $hostAddr --port $port
