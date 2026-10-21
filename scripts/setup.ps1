param([string]$Python='python')
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
& $Python --version
if($LASTEXITCODE){throw 'Supply -Python with Python 3.12 executable'}
& $Python -m venv .venv
& .venv/Scripts/python.exe -m pip install --no-cache-dir setuptools==80.9.0 wheel==0.45.1
& .venv/Scripts/python.exe -m pip install --no-build-isolation --no-cache-dir -r requirements.lock.txt
if($LASTEXITCODE){throw 'Core dependency installation failed'}
& $Python -m venv .venv-jianying
& .venv-jianying/Scripts/python.exe -m pip install --no-cache-dir -r requirements-jianying.lock.txt
if($LASTEXITCODE){throw 'Draft dependency installation failed'}
npm ci --cache .local/npm-cache --no-audit --no-fund
if($LASTEXITCODE){throw 'Node installation failed'}
if(!(Test-Path config.local.json)){Copy-Item config.example.json config.local.json}
& .venv/Scripts/python.exe scripts/doctor.py
