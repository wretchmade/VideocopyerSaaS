"""Final implementation-only measurements against the frozen old baseline."""
import copy,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for case in (720,1080,'room'):
    for n in range(1 if case=='room' else 5):
        folder=ROOT/f'.local/compositing-benchmark/final-fast-{case}-{n}'
        if (folder/'benchmark.json').exists():continue
        source='room-original' if case=='room' else 'ordinary-'+str(case)
        subprocess.run([sys.executable,str(ROOT/'scripts/compositing_benchmark.py'),'--document',
                        str(ROOT/f'.local/compositing-benchmark/fixtures/{source}.json'),'--output',str(folder)],check=True,cwd=ROOT)
doc=json.loads((ROOT/'.local/compositing-benchmark/fixtures/ordinary-1080.json').read_text(encoding='utf8'))
doc['frames']=360
doc['layers'][0]['end']=180
doc['layers'][1].update(start=180,end=360)
for layer in doc['layers'][2:]:layer['end']=360
doc['audio'][0]['end']=360
short=ROOT/'.local/compositing-benchmark/fixtures/ordinary-1080-short.json'
short.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf8')
folder=ROOT/'.local/compositing-benchmark/final-fast-1080-short'
if not (folder/'benchmark.json').exists():
    subprocess.run([sys.executable,str(ROOT/'scripts/compositing_benchmark.py'),'--document',str(short),'--output',str(folder)],check=True,cwd=ROOT)
