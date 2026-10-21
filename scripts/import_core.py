"""One-time, allowlisted import; never modifies the source tree."""
import hashlib, json, shutil, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(r'C:\Users\Administrator\.codex\worktrees\929d\VideoCopyer\commercial-d')
records = []
groups = [('services/api/app/workbench_d/commercial', 'server/app/workbench_d/commercial'), ('docs/commercial', 'docs/upstream-commercial')]
for src, dst in groups:
    for p in (SOURCE / src).rglob('*'):
        if not p.is_file() or '__pycache__' in p.parts or p.suffix not in {'.py', '.mjs', '.json', '.md', '.xml'}:
            continue
        target = ROOT / dst / p.relative_to(SOURCE / src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)
        records.append({'source': str(p), 'target': target.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
for name in ['THIRD-PARTY-NOTICES.md', 'JIANYING-NOTICE.md', 'requirements.lock.txt', 'requirements-jianying.lock.txt']:
    p = SOURCE / 'plugins/workbench-d' / name
    target = ROOT / 'docs/upstream-commercial' / name
    shutil.copyfile(p, target)
    records.append({'source': str(p), 'target': target.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
(ROOT / 'docs/evidence/core-import.json').write_text(json.dumps(records, indent=2), encoding='utf8')
tag = json.load(urllib.request.urlopen('https://api.github.com/repos/openai/codex/git/ref/tags/rust-v0.163.0'))
(ROOT / 'docs/evidence/codex-tag.json').write_text(json.dumps(tag, indent=2))
for url, name in [('https://raw.githubusercontent.com/openai/codex/rust-v0.163.0/codex-rs/app-server/README.md', 'codex-app-server.md'), ('https://raw.githubusercontent.com/openai/codex/rust-v0.163.0/LICENSE', 'codex-LICENSE')]:
    (ROOT / 'docs/evidence' / name).write_bytes(urllib.request.urlopen(url).read())
print('Imported', len(records), 'files. Codex tag:', tag['object'])
