"""Explicit import from D's pre-core SQLite workspace contract; read-only source."""
import json,os,sqlite3
from fractions import Fraction
from pathlib import Path
from .render import sha
from .schema import upgrade


def read_workspace(workspace_id,revision):
    path=os.environ.get('D_LEGACY_DATABASE')
    if not path: raise ValueError('Set D_LEGACY_DATABASE to the existing D SQLite database')
    root=Path(os.environ.get('D_LEGACY_ASSETS','')).resolve()
    if not os.environ.get('D_LEGACY_ASSETS'):raise ValueError('Set D_LEGACY_ASSETS to the existing D asset root')
    connection=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    connection.row_factory=sqlite3.Row
    try:
        row=connection.execute('SELECT * FROM template_workspaces WHERE id=?',(workspace_id,)).fetchone()
        if not row:raise ValueError('D workspace not found')
        if row['revision']!=revision:raise ValueError('REVISION_CONFLICT: legacy D workspace changed')
        if row['active_run_id']:
            run=connection.execute('SELECT status FROM workflow_runs WHERE id=?',(row['active_run_id'],)).fetchone()
            if run and run['status'] in ('PENDING','RUNNING','QUEUED'):raise ValueError('Pause the source D workspace before importing')
        document=json.loads(row['document']);composition=document.get('specs',{}).get('composition')
        if not composition:raise ValueError('D workspace has no composition contract')
        assets=[dict(a) for a in connection.execute('SELECT * FROM assets WHERE project_id=?',(row['project_id'],))]
        result=convert(composition,assets,root)
        return dict(name=row['title'],document=result,source=dict(workspace_id=workspace_id,revision=revision,
                    database=str(Path(path).resolve()),document_sha256=__import__('hashlib').sha256(row['document'].encode()).hexdigest()))
    finally:connection.close()


def convert(c,assets,root):
    """Convert supported semantics exactly; refuse unimplemented fields, never flatten silently."""
    for key in ('captions','transitions','events','selections','audio_tracks','audio_slot'):
        if c.get(key):raise ValueError(f'Legacy {key} needs explicit D Project authoring; import refused')
    raw=c.get('fps',24);rate=Fraction(raw['num'],raw.get('den',1)) if isinstance(raw,dict) else Fraction(raw)
    def frame(seconds):
        value=Fraction(str(seconds))*rate
        return (2*value.numerator+value.denominator)//(2*value.denominator)
    result=dict(width=c['width'],height=c['height'],fps=dict(num=rate.numerator,den=rate.denominator),frames=frame(c['duration']),
                background=c.get('background','#000000'),assets=[],layers=[],audio=[])
    used=set()
    for number,l in enumerate(c['layers']):
        for key in ('motion','animation','crop','effects','decoration','sampling','content_fit','event_id','selection_id'):
            if l.get(key):raise ValueError(f'Legacy layer {l["id"]}: {key} needs explicit conversion')
        if l.get('target') or l.get('fit_duration') or l.get('playback_rate',1)!=1 or l.get('playback') not in (None,'once-start'):raise ValueError('Legacy retiming/target requires explicit conversion')
        if l.get('source_end') is not None or l.get('video_stream',0)!=0 or l.get('audio_stream',0)!=0:raise ValueError('Legacy source end or nondefault stream requires explicit conversion')
        if l.get('kind')=='text':raise ValueError('Legacy text must name licensed font assets before conversion')
        anchor=l.get('anchor') or {}
        if any(v not in (None,0,'top-left') for v in anchor.values()):raise ValueError('Legacy anchor must be converted explicitly')
        pose=l.get('position',{})
        out=dict(id=l['id'],kind=l['kind'],asset=l.get('asset_id'),start=frame(l['start']),end=frame(l['end']),
                 source_start=frame(l.get('source_start',0)),track=number,x=pose.get('x',0),y=pose.get('y',0),
                 opacity=pose.get('opacity',1),rotation=pose.get('rotation',0),scale=pose.get('scale',1),
                 width=l['width'],height=l['height'],color=l.get('color','#ffffff'),fit=l.get('fit','contain'),
                 fade_in=frame(l.get('fade_in',0)),fade_out=frame(l.get('fade_out',0)))
        if out['asset']:used.add(out['asset'])
        if l.get('source_audio'):result['audio'].append(dict(asset=out['asset'],start=out['start'],end=out['end'],source_start=out['source_start']))
        result['layers'].append(out)
    if c.get('audio_asset_id'):
        used.add(c['audio_asset_id']);result['audio'].append(dict(asset=c['audio_asset_id'],start=0,end=result['frames']))
    by_id={a['id']:a for a in assets}
    for aid in sorted(used):
        if aid not in by_id:raise ValueError('workspace asset missing')
        a=by_id[aid];path=(root/a['storage_key']).resolve()
        if not path.is_relative_to(root) or not path.is_file():raise ValueError('legacy asset path missing or outside asset root')
        metadata=json.loads(a.get('metadata_json') or '{}')
        provenance=metadata.get('provenance',{})
        if not provenance.get('license') or not provenance.get('source'):raise ValueError(f'Legacy asset {aid} needs recorded license and source in metadata_json.provenance')
        digest=sha(path)
        if a.get('checksum') and a['checksum']!=digest:raise ValueError('legacy asset checksum mismatch')
        result['assets'].append(dict(id=aid,kind=a['type'],path=str(path),sha256=digest,**{k:provenance[k] for k in ('license','source')}))
    return upgrade(result).model_dump(mode='json')
