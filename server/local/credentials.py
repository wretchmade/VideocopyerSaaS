"""Read only the operator-selected credential reference; no legacy runtime imports."""
import json, os, subprocess
from pathlib import Path
from .config import CONFIG

def profile():
    path=CONFIG.get('media_profile')
    if not path: raise ValueError('尚未配置媒体账户')
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def media_endpoint(): return profile()['endpoints']['ark.seedance']['config']

def media_key():
    p=profile(); ref=p['endpoints']['ark.seedance']['config']['apiKey']
    if ref['store']!='platform': raise ValueError('仅支持明确配置的 Windows 凭据引用')
    service=p['credentials'][ref['store']].get('config',{}).get('service','hypit')
    return windows_secret(service,ref['key'])

def windows_secret(service,account):
    # This selected account uses Windows PasswordVault, not Credential Manager.
    # Arguments travel over stdin; stdout is consumed in memory and never logged.
    script="""$ErrorActionPreference='Stop'; $r=[Console]::In.ReadToEnd()|ConvertFrom-Json; $null=[Windows.Security.Credentials.PasswordVault,Windows.Security.Credentials,ContentType=WindowsRuntime]; $v=New-Object Windows.Security.Credentials.PasswordVault; $c=$v.Retrieve($r.service,$r.account); $c.RetrievePassword(); [Console]::Write($c.Password)"""
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],input=json.dumps({'service':service,'account':account}),capture_output=True,text=True,encoding='utf8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=20)
    if result.returncode==0 and result.stdout: return result.stdout.lstrip('\ufeff')
    raise ValueError('所选 Windows PasswordVault 凭据不可用')

def planning_key():
    p=CONFIG.get('planning',{})
    return media_key() if p.get('use_media_key') else os.environ.get(p.get('key_env','VIDEOCOPYER_PLANNING_KEY'),'')

def cos_values():
    p=CONFIG.get('cos_env_file')
    if not p: return {}
    values={}
    for line in Path(p).read_text(encoding='utf-8-sig').splitlines():
        if '=' not in line or line.lstrip().startswith('#'): continue
        k,v=line.split('=',1)
        if k.strip().startswith('VIDEO_WORKBENCH_COS_'): values[k.strip().removeprefix('VIDEO_WORKBENCH_COS_')]=v.strip().strip('\"\'')
    return values
