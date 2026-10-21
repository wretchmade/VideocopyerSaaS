$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$record=Join-Path $root '.local/server-process.json'
if(!(Test-Path $record)){Write-Output 'No managed server recorded';exit 0}
$state=Get-Content $record -Raw|ConvertFrom-Json
$proc=Get-Process -Id $state.pid -ErrorAction SilentlyContinue
if($proc -and $proc.Path -eq $state.python -and $proc.StartTime.ToUniversalTime().ToString('o') -eq $state.started){
  # Limit termination to this recorded server's descendants, never unrelated Python jobs.
  & taskkill.exe /PID $state.pid /T /F | Out-Null
  if($LASTEXITCODE){throw 'Windows did not stop the complete recorded service tree. Check process permissions; do not assume the service stopped.'}
  Write-Output 'Stopped VideoCopyer; remote requests remain recorded for recovery.'
}else{Write-Output 'Recorded server is no longer running; no process stopped.'}
