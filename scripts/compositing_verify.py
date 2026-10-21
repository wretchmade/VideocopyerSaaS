"""Run offline composition/upstream checks with the deployed audited media tools."""
import json,os,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
cfg=json.loads((ROOT/'config.local.json').read_text(encoding='utf-8-sig'))
folder=ROOT/'.local'/('compositing-tests-'+uuid.uuid4().hex)
folder.mkdir(parents=True)
os.environ.update(PYTHONUTF8='1',PYTHONPATH=str(ROOT/'server'),D_FFMPEG=cfg['ffmpeg'],D_FFPROBE=cfg['ffprobe'],
                  D_TEST_FONT=cfg['font'],D_JIANYING_PYTHON=str(ROOT/'.venv-jianying/Scripts/python.exe'),
                  D_HEAVY_ROOT=str(folder/'resources'))
import pytest
raise SystemExit(pytest.main([*(sys.argv[1:] or ['tests/test_compositing.py','tests/upstream']),'-q',
                             '--basetemp',str(folder/'cases'),'--junitxml',str(ROOT/'docs/evidence/compositing/tests.xml')]))
