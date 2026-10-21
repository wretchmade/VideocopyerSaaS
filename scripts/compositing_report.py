"""Summarize measured samples; five observations are median/worst, never a p95."""
import hashlib,json,platform,statistics
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1]
data=ROOT/'.local/compositing-benchmark'
def code_hash(folder):
    return hashlib.sha256(b''.join(p.read_bytes() for p in sorted(folder.iterdir()) if p.suffix in ('.py','.mjs'))).hexdigest()
current_hash=code_hash(ROOT/'server/app/workbench_d/commercial')
cases={}
for case in (720,1080,'room'):
    groups={}
    for route in ('baseline','fast'):
        paths=sorted(data.glob(f'repeat-{route}-{case}-*/benchmark.json'))
        final=sorted(data.glob(f'final-{route}-{case}-[0-9]/benchmark.json'))
        if final:paths=final
        values=[json.loads(p.read_text(encoding='utf8')) for p in paths]
        if not values:continue
        if route=='fast':assert all(v.get('implementation_sha256')==current_hash for v in values),'Rerun optimized samples against the final implementation'
        if case in (720,1080):assert len(values)==5,'Five repetitions required'
        groups[route]={'samples':len(values),'wall_median_seconds':statistics.median(v['wall_seconds'] for v in values),
                       'wall_worst_seconds':max(v['wall_seconds'] for v in values),
                       'peak_tree_rss_bytes':max(v['tree_peak_rss_bytes'] for v in values),
                       'peak_temp_bytes':max(v['temp_peak_bytes'] for v in values),
                       'cpu_median_seconds':statistics.median(v['sampled_tree_cpu_seconds'] for v in values),
                       'png_counts':sorted({v['png_count'] for v in values}),
                       'video_encodes':sorted({v['result'].get('video_encodes',1) for v in values}),
                       'output_hashes':sorted({v['result']['sha256'] for v in values}),
                       'output_bytes':sorted({v['output_bytes'] for v in values}),
                       'routes':sorted({v['result'].get('render_plan',{}).get('route','legacy-png') for v in values}),
                       'fallback_reasons':sorted({r for v in values for r in v['result'].get('render_plan',{}).get('fallback_reasons',[])}),
                       'phase_medians':{key:statistics.median(v['phases_seconds'].get(key,0) for v in values) for key in {k for v in values for k in v['phases_seconds']}},
                       'evidence':[str(p.relative_to(ROOT)) for p in paths]}
    if len(groups)==2:
        a,b=groups['baseline'],groups['fast']
        groups['comparison']={'time_reduction_percent':100*(1-b['wall_median_seconds']/a['wall_median_seconds']),
                              'temp_reduction_percent':100*(1-b['peak_temp_bytes']/a['peak_temp_bytes']),
                              'all_movie_files_identical':a['output_hashes']==b['output_hashes'] and len(a['output_hashes'])==1}
    cases[str(case)]=groups
report={'machine':{'os':platform.platform(),'logical_cpus':psutil.cpu_count(),'physical_cpus':psutil.cpu_count(logical=False),'ram_bytes':psutil.virtual_memory().total},
        'local_measurement_not_cloud_capacity':True,'provider_requests':0,
        'baseline_code_sha256':code_hash(ROOT/'.local/compositing-backups/20261020-160347/server/app/workbench_d/commercial'),
        'new_code_sha256':current_hash,
        'sampling':{'interval_seconds':.05,'cpu':'sampled process-tree CPU; very short processes may be missed','rss':'sum, shared pages can be double-counted',
                    'temp':'benchmark directory excluding output.*; original inputs, final/pending output, external bounded stderr log excluded'},
        'cases':cases}
report['fixed_case_coverage']={'ordinary_fast_cases':2,'baseline_cases':3,
                              'compatibility_case':'room original: explicit crossfade',
                              'not_a_production_hit_rate':True,
                              'subtitle_edit_static_cache_hits':'1/2 states (Logo hit, changed text miss), asserted in tests',
                              'subtitle_edit_new_generation_requests':0,'segment_cache_implemented':False}
short=data/'final-fast-1080-short/benchmark.json'
if short.exists():
    v=json.loads(short.read_text(encoding='utf8'))
    report['duration_memory_check']={'short_frames':v['result']['frames'],'short_peak_rss_bytes':v['tree_peak_rss_bytes'],
                                     'long_frames':1800,'long_peak_rss_bytes':cases['1080']['fast']['peak_tree_rss_bytes'],
                                     'scope':'same 1080p sources and layers; one short run versus five long runs, no cloud capacity claim'}
target=ROOT/'docs/evidence/compositing/performance.json';target.write_text(json.dumps(report,indent=2),encoding='utf8')
lines=['# 本机合成基准','',f"机器：{report['machine']['logical_cpus']} 逻辑 CPU，{report['machine']['ram_bytes']/1024**3:.1f} GiB RAM；不是 8C/32G 云端容量验收。",'',
       '| 样本 | 次数（旧/新） | 旧中位/最慢 s | 新中位/最慢 s | 耗时降低 | 临时盘峰值旧/新 MB | 新整树 RSS 峰值 MB | PNG 旧/新 |',
       '|---|---:|---:|---:|---:|---:|---:|---|']
for name,g in cases.items():
    if 'comparison' not in g:continue
    a,b=g['baseline'],g['fast']
    lines.append(f"| {name} | {a['samples']}/{b['samples']} | {a['wall_median_seconds']:.2f}/{a['wall_worst_seconds']:.2f} | {b['wall_median_seconds']:.2f}/{b['wall_worst_seconds']:.2f} | {g['comparison']['time_reduction_percent']:.1f}% | {a['peak_temp_bytes']/1e6:.2f}/{b['peak_temp_bytes']/1e6:.3f} | {b['peak_tree_rss_bytes']/1e6:.1f} | {a['png_counts']}/{b['png_counts']} |")
lines+=['','720 = 12 秒 1280×720，1080 = 60 秒 1920×1080；均为 30fps，普通剪辑、中文字幕、半透明 Logo、48k 合成音频（测试配音通道）。room = 原房间工程（包含交叉淡化和原音轨），属于明确回退覆盖。','',
        '重复均为新目录、冷图层缓存，顺序运行。旧版本来自切换前不可变备份；编码器、码率公式、输出规格、字体保持不变。新路线含 4 核亲和限制。五次样本只报告中位数和最慢值，不包装为可靠 p95。','',
        '临时盘排除原始输入及 output.*（含未完成输出），stderr 在系统临时文件中按 16MB 终止阈值监测（50ms 轮询，可能短暂超量）；RSS 对共享页可能重复计数。采样 CPU 可能遗漏寿命短于 50ms 的子进程，新路线另有 Windows Job 精确子树 CPU 记录。','',
        f"原房间工程仍走 PNG 兼容路线，4 逻辑核预算下该样本为 {cases['room']['baseline']['wall_median_seconds']:.2f}s → {cases['room']['fast']['wall_median_seconds']:.2f}s（单次对照）；这是当前明确的性能回退，不属于已优化范围。普通路径的单次编码和原输出参数保持不变。",'',
        '详细阶段、代码指纹、回退原因、逐次证据见 [performance.json](evidence/compositing/performance.json)。']
if report.get('duration_memory_check'):
    m=report['duration_memory_check']
    lines+=['',f"同 1080p 来源与图层，12 秒峰值 {m['short_peak_rss_bytes']/1e6:.1f} MB，60 秒峰值 {m['long_peak_rss_bytes']/1e6:.1f} MB。该局部样本未随总帧数线性增长；不推断任意工程或云端并发容量。"]
(ROOT/'docs/COMPOSITING-BENCHMARK.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
print(json.dumps({'cases':{k:v.get('comparison') for k,v in cases.items()},'report':str(target)}))
