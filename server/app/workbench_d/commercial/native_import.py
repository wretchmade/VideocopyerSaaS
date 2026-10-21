"""Conservative plaintext import. Unsupported semantics are errors, never discarded."""
from pathlib import Path
from fractions import Fraction
import json
from .schema import Project
from .render import sha


def decode(native,folder,licenses):
    if not isinstance(native,dict) or not isinstance(native.get('tracks'),list):raise ValueError('UNSUPPORTED_NATIVE_SCHEMA')
    fps=native.get('fps',30);canvas=native.get('canvas_config',{});w=canvas.get('width');h=canvas.get('height')
    if not isinstance(fps,int) or not w or not h:raise ValueError('UNSUPPORTED_NATIVE_CLOCK_OR_CANVAS')
    def frame(us):
        exact=Fraction(us*fps,1000000);value=round(exact)
        if abs(exact-value)>Fraction(fps,1000000):raise ValueError('MIGRATION_REQUIRED: time is not D frame aligned')
        return value
    materials=native.get('materials',{});lookup={m['id']:(kind,m) for kind,rows in materials.items() if isinstance(rows,list) for m in rows if isinstance(m,dict) and 'id' in m}
    assets=[];layers=[];audio=[];duration=frame(native.get('duration',0));seen={}
    def asset(mid,material,kind):
        if mid in seen:return seen[mid]
        path=Path(material['path']);path=path if path.is_absolute() else folder/path
        if not path.is_file():raise ValueError('MISSING_NATIVE_ASSET: '+str(path))
        rights=licenses.get(mid)
        if not rights or not rights.get('license') or not rights.get('source'):raise ValueError('ASSET_LICENSE_REQUIRED: '+mid)
        aid='native_'+str(len(assets));assets.append(dict(id=aid,kind=kind,path=str(path.resolve()),sha256=sha(path),license=rights['license'],source=rights['source']));seen[mid]=aid;return aid
    for order,track in enumerate(native['tracks']):
        if track['type'] not in ('video','audio','text'):raise ValueError('UNSUPPORTED_NATIVE_TRACK: '+track['type'])
        for s in track['segments']:
            if s.get('common_keyframes') or s.get('keyframe_refs') or s.get('speed',1)!=1:raise ValueError('MIGRATION_REQUIRED: animation or retiming')
            for ref in s.get('extra_material_refs',[]):
                kind,extra=lookup.get(ref,('unknown',{}))
                if kind not in ('speeds','canvases','sound_channel_mappings','material_colors','vocal_separations'):raise ValueError('MIGRATION_REQUIRED: native effect '+kind)
                if kind=='speeds' and extra.get('speed',1)!=1:raise ValueError('MIGRATION_REQUIRED: native speed')
                if kind=='canvases' and extra.get('type') not in (None,'canvas_color'):raise ValueError('MIGRATION_REQUIRED: canvas')
            kind,m=lookup.get(s['material_id'],(None,None))
            if m is None:raise ValueError('MISSING_NATIVE_MATERIAL')
            tr=s['target_timerange'];start=frame(tr['start']);end=frame(tr['start']+tr['duration']);duration=max(duration,end)
            source=frame((s.get('source_timerange') or {}).get('start',0))
            if track['type']=='audio':audio.append(dict(asset=asset(m['id'],m,'audio'),start=start,end=end,source_start=source,volume=s.get('volume',1)));continue
            clip=s.get('clip') or {};scale=clip.get('scale',{'x':1,'y':1});translation=clip.get('transform',{'x':0,'y':0})
            if scale!={'x':1,'y':1} or translation!={'x':0,'y':0} or clip.get('rotation',0) or any((clip.get('flip') or {}).values()):raise ValueError('MIGRATION_REQUIRED: transformed native clip; use an explicit D mapping')
            if track['type']=='text':raise ValueError('MIGRATION_REQUIRED: native text needs an explicit font/layout mapping; D sidecars support lossless editable text import')
            crop=m.get('crop') or {}
            if crop and any(crop.get(k,default)!=default for k,default in {'upper_left_x':0,'upper_left_y':0,'upper_right_x':1,'upper_right_y':0,'lower_left_x':0,'lower_left_y':1,'lower_right_x':1,'lower_right_y':1}.items()):raise ValueError('MIGRATION_REQUIRED: native crop')
            media_kind='image' if m.get('type')=='photo' else 'video'
            if s.get('volume',0) and media_kind=='video':raise ValueError('MIGRATION_REQUIRED: embedded video audio must be explicitly split')
            layers.append(dict(id='clip_'+str(len(layers)),kind=media_kind,asset=asset(m['id'],m,media_kind),start=start,end=end,source_start=source,track=order,width=w,height=h,opacity=clip.get('alpha',1)))
    return Project(width=w,height=h,frames=duration,fps=dict(num=fps,den=1),assets=assets,layers=layers,audio=audio).model_dump(mode='json')
