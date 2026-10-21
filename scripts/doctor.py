import importlib.metadata, json, shutil, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from local.config import CONFIG,DATA
report={'python':sys.version.split()[0],'data_dir':str(DATA),'dependencies':{k:importlib.metadata.version(k) for k in ['fastapi','pydantic','pillow','sqlalchemy']},'ffmpeg':CONFIG.get('ffmpeg') or shutil.which('ffmpeg'),'ffprobe':CONFIG.get('ffprobe') or shutil.which('ffprobe'),'node':shutil.which('node'),'font_available':Path(CONFIG.get('font','')).is_file(),'planning_model':CONFIG.get('planning',{}).get('model'),'budget_cny':CONFIG.get('test_budget_cny'),'credential':'not inspected','jianying_python':(ROOT/'.venv-jianying/Scripts/python.exe').is_file()}
try:report['codex']=subprocess.check_output([shutil.which('node'),str(ROOT/'node_modules/@openai/codex/bin/codex.js'),'--version'],text=True).strip()
except Exception:report['codex']='unavailable'
print(json.dumps(report,ensure_ascii=False,indent=2))
