$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$env:PYTHONUTF8='1'
$env:PYTHONPATH=Join-Path $root 'server'
$testRun=Join-Path '.local' ('verify-'+[guid]::NewGuid().ToString('N'))
& .venv/Scripts/python.exe -m pytest tests/test_control.py tests/test_recovery.py tests/test_workflow.py tests/test_parity.py tests/test_parity_tools.py tests/test_templates.py tests/test_security.py tests/test_codex_config.py tests/test_native_harness.py -q --basetemp $testRun --junitxml .local/verification.xml
if($LASTEXITCODE){throw 'Control tests failed'}
& .venv/Scripts/python.exe scripts/gateway_pool_probe.py
if($LASTEXITCODE){throw 'Gateway connection reuse check failed'}
node scripts/workflow-graph-test.mjs
if($LASTEXITCODE){throw 'Workflow graph tests failed'}
npm run build
if($LASTEXITCODE){throw 'Web build failed'}
Write-Output 'Free checks passed. parity_web_probe.py is an isolated free protocol test; legacy browser-test.mjs calls paid providers.'
