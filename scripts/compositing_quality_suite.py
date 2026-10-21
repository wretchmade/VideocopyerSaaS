"""Final encoded-frame and complete SSIM comparisons, run after timed benchmarks."""
import json
from pathlib import Path
from compositing_quality import compare,ROOT
base=ROOT/'.local/compositing-benchmark'
for case,doc in [('720','ordinary-720'),('1080','ordinary-1080'),('room','room-original'),('room-hardcut','room-hardcut')]:
    if case=='room-hardcut':
        old=base/'quality-room-hardcut-baseline-0/benchmark.json';new=base/'quality-room-hardcut-fast-0/benchmark.json'
    else:
        old=base/f'repeat-baseline-{case}-0/benchmark.json';new=base/f'final-fast-{case}-0/benchmark.json'
    compare(json.loads(old.read_text(encoding='utf8'))['result'],json.loads(new.read_text(encoding='utf8'))['result'],
            json.loads((base/f'fixtures/{doc}.json').read_text(encoding='utf8')),'quality-'+case)
