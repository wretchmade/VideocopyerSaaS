param([switch]$NoBuild,[switch]$Foreground)
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$python=Join-Path $root '.venv\Scripts\python.exe'
if(!(Test-Path $python)){throw 'Run scripts/setup.ps1 first'}
if(!$NoBuild){npm run build;if($LASTEXITCODE){throw 'Frontend build failed'}}
New-Item -ItemType Directory -Force '.local'|Out-Null
$env:PYTHONPATH=Join-Path $root 'server'
$env:PYTHONUTF8='1'
$port=8765
$agentRuntime='codex'
$configPath=if($env:VC_CONFIG){$env:VC_CONFIG}else{'config.local.json'}
if(Test-Path -LiteralPath $configPath){
  $config=Get-Content -LiteralPath $configPath -Raw|ConvertFrom-Json
  $port=$config.port
  if($config.agent_runtime){$agentRuntime=$config.agent_runtime}
}
if($agentRuntime -notin @('codex','native')){throw 'agent_runtime must be codex or native'}
$listenerProbe=New-Object Net.Sockets.TcpClient
try { $listenerProbe.Connect('127.0.0.1',$port); $alreadyListening=$true } catch { $alreadyListening=$false } finally { $listenerProbe.Dispose() }
if($alreadyListening){
  $health=Invoke-RestMethod "http://127.0.0.1:$port/api/bootstrap" -TimeoutSec 2
  if($health.agent_runtime -ne $agentRuntime){throw 'Agent runtime changed. Run scripts/stop.ps1, then start again.'}
  Write-Output "Already listening: http://127.0.0.1:$port";exit 0
}
if($Foreground){& $python -m uvicorn local.main:app --host 127.0.0.1 --port $port;exit $LASTEXITCODE}
$proc=Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','local.main:app','--host','127.0.0.1','--port',"$port") -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput "$root\.local\server.out.log" -RedirectStandardError "$root\.local\server.err.log"
$ready=$false
for($attempt=0;$attempt -lt 40;$attempt++){
  Start-Sleep -Milliseconds 250
  if($proc.HasExited){throw 'Server exited during startup; inspect .local/server.err.log. Previous process record preserved.'}
  try { $health=Invoke-RestMethod "http://127.0.0.1:$port/api/bootstrap" -TimeoutSec 1; $ready=($health.agent_runtime -eq $agentRuntime -and ($agentRuntime -eq 'native' -or $health.codex_version -eq '0.163.0')) } catch { $ready=$false }
  if($ready){break}
}
if(!$ready){throw 'Server did not pass readiness check; inspect .local/server.err.log. Previous process record preserved.'}
@{pid=$proc.Id;started=$proc.StartTime.ToUniversalTime().ToString('o');python=$python}|ConvertTo-Json|Set-Content '.local/server-process.json'
Write-Output "VideoCopyer: http://127.0.0.1:$port"
