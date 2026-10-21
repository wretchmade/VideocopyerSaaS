"""Sequential cold render repetitions. No overlapping measurements or provider calls."""
import subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
baseline=ROOT/'.local/compositing-backups/20261020-160347/server'
for height in (720,1080,'room'):
    for route,source in [('baseline',baseline),('fast',ROOT/'server')]:
        for number in range(1 if height=='room' else 5):
            out=ROOT/f'.local/compositing-benchmark/repeat-{route}-{height}-{number}'
            if (out/'benchmark.json').exists():continue
            subprocess.run([sys.executable,str(ROOT/'scripts/compositing_benchmark.py'),'--source',str(source),
                            '--document',str(ROOT/f'.local/compositing-benchmark/fixtures/{("room-original" if height=="room" else "ordinary-"+str(height))}.json'),
                            '--output',str(out)],check=True,cwd=ROOT)
