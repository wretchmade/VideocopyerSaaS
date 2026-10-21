import json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(os.environ.get('VC_CONFIG', ROOT / 'config.local.json'))
CONFIG = json.loads((CONFIG_PATH if CONFIG_PATH.is_file() else ROOT / 'config.example.json').read_text(encoding='utf-8-sig'))
DATA = Path(os.environ.get('VC_DATA', CONFIG.get('data_dir', '.local/data')))
if not DATA.is_absolute(): DATA = ROOT / DATA
DATA = DATA.resolve()
DATA.mkdir(parents=True, exist_ok=True)
OWNER = 'local-owner'
PORT = int(CONFIG.get('port', 8765))

def contained(path, root=DATA):
    p = Path(path).resolve()
    if not p.is_relative_to(Path(root).resolve()): raise ValueError('文件不属于本应用存储')
    return p
