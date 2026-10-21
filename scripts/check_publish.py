"""Check staged source for private runtime files and common credential signatures.

This is a heuristic release guard, not a guarantee that every secret is detected.
Only filenames, line numbers and rule names are printed, never matched secrets.
"""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(
        ['git', '-c', 'safe.directory=' + ROOT.as_posix(), *args], cwd=ROOT)


def main():
    names = [p.decode('utf8') for p in git('diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z').split(b'\0') if p]
    rules = {
        'private-key': r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
        'github-token': r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b',
        'provider-token': r'\bsk-[A-Za-z0-9_-]{24,}\b',
        'cloud-access-id': r'\b(?:AKIA[A-Z0-9]{16}|AKID[A-Za-z0-9]{28,})\b',
        'signed-media-url': r'(?i)(?:q-signature|x-amz-signature|x-cos-security-token)=[A-Za-z0-9%+/_-]{16,}',
        'url-password': r'(?i)(?:https?|postgres(?:ql)?(?:\+psycopg)?)://[^\s/:]+:([^\s/@]+)@',
    }
    failures = []
    total = 0
    for name in names:
        path = Path(name)
        if any(p in {'.local', '.venv', '.venv-jianying', 'node_modules', '__pycache__', 'dist', '.pytest_cache'} for p in path.parts) or (
            path.name.startswith('.env') and path.name != '.env.example'
        ) or path.name == 'config.local.json' or (
            'evidence' in path.parts and name != 'docs/evidence/codex-LICENSE'
        ) or path.suffix.lower() in {'.db', '.sqlite', '.sqlite3', '.pem', '.key', '.pfx', '.p12', '.pyc', '.log', '.tsbuildinfo'}:
            failures.append({'file': name, 'rule': 'private-runtime-file'})
        data = git('show', ':' + name)
        total += len(data)
        if len(data) > 10 * 1024 * 1024:
            failures.append({'file': name, 'rule': 'oversized-source-file'})
        if b'\0' in data:
            continue
        text = data.decode('utf8', errors='replace')
        for rule, pattern in rules.items():
            for match in re.finditer(pattern, text):
                # Documented placeholder DSNs are not real credentials.
                if rule == 'url-password' and match.group(1) in {'password', 'example', 'changeme'}:
                    continue
                failures.append({'file': name, 'line': text.count('\n', 0, match.start()) + 1, 'rule': rule})
    print(json.dumps({'staged_files': len(names), 'bytes': total, 'findings': failures}, ensure_ascii=False, indent=2))
    return 1 if failures or not names else 0


if __name__ == '__main__':
    raise SystemExit(main())
