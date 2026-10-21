"""Install a verified exported draft into a NEW directory; no overwrite or arbitrary extraction."""
import argparse, hashlib, json, os, shutil, subprocess, sys, zipfile
from pathlib import Path

def install(package,destination):
    dest=Path(destination).expanduser().resolve()
    if dest.exists():raise ValueError('目标目录已存在；请选择一个新的草稿子目录')
    if os.name=='nt':
        result=subprocess.run(['powershell.exe','-NoProfile','-Command','if(Get-Process JianyingPro,CapCut -ErrorAction SilentlyContinue){exit 3}'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise ValueError('请先关闭剪映/CapCut')
    with zipfile.ZipFile(package) as z:
        manifest=json.loads(z.read('manifest.json'))
        entries={}
        for name,expected in manifest['files'].items():
            p=Path(name)
            if p.is_absolute() or '..' in p.parts or ':' in name or '\\' in name:raise ValueError('包内路径无效')
            data=z.read('draft/'+name)
            if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('哈希校验失败：'+name)
            entries[name]=data
        doc=json.loads(entries['d-project.json']);old_roots=set()
        for a in doc['assets']:
            p=Path(a['path'])
            if 'media' in p.parts:old_roots.add(str(p.parent.parent).replace('\\','/'))
        native=json.loads(entries['d-manifest.json']);old_roots.add(native['path'].replace('\\','/'))
        def rewrite(value):
            if isinstance(value,str):
                normalized=value.replace('\\','/')
                for old in sorted(old_roots,key=len,reverse=True):
                    if normalized==old or normalized.startswith(old+'/'):return dest.as_posix()+normalized[len(old):]
                # Some native text contents contain encoded JSON with font paths.
                if value.startswith(('{','[')):
                    try:return json.dumps(rewrite(json.loads(value)),ensure_ascii=False)
                    except ValueError:pass
                return value
            if isinstance(value,list):return [rewrite(x) for x in value]
            if isinstance(value,dict):return {k:rewrite(v) for k,v in value.items()}
            return value
        stage=dest.with_name(dest.name+'.install-'+os.urandom(4).hex())
        stage.mkdir(parents=True,exist_ok=False)
        try:
            for name,data in entries.items():
                target=stage/name;target.parent.mkdir(parents=True,exist_ok=True)
                if name.endswith('.json'):data=json.dumps(rewrite(json.loads(data)),ensure_ascii=False,indent=2).encode()
                target.write_bytes(data)
            dm_path=stage/'d-manifest.json'
            dm=json.loads(dm_path.read_text(encoding='utf8'))
            dm['path']=str(dest)
            dm['nativeHash']=hashlib.sha256((stage/'draft_content.json').read_bytes()).hexdigest()
            document=json.loads((stage/'d-project.json').read_text(encoding='utf8'))
            dm['documentHash']=hashlib.sha256(json.dumps(document,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
            dm['files']={name:hashlib.sha256((stage/name).read_bytes()).hexdigest() for name in dm['files'] if (stage/name).is_file()}
            dm_path.write_text(json.dumps(dm,ensure_ascii=False,indent=2),encoding='utf8')
            (stage/'installation-receipt.json').write_text(json.dumps({'source':manifest,'destination':str(dest),'files':{p.relative_to(stage).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in stage.rglob('*') if p.is_file()}},ensure_ascii=False,indent=2),encoding='utf8')
            # No overwrite: Windows rename fails when destination already exists.
            if dest.exists():raise ValueError('目标目录已存在')
            stage.rename(dest)
        except BaseException:
            if stage.exists() and stage.parent==dest.parent and stage.name.startswith(dest.name+'.install-'):shutil.rmtree(stage)
            raise
    return {'installed':str(dest),'editor_ui_verified':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--zip',default=str(Path(__file__).with_name('jianying.zip')));p.add_argument('--destination',required=True);a=p.parse_args()
    try:print(json.dumps(install(a.zip,a.destination),ensure_ascii=False))
    except Exception as exc:print(str(exc),file=sys.stderr);sys.exit(1)
