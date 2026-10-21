"""Versioned evidence: final encoded screenshots and explicit legacy references."""
import json,os
from pathlib import Path
from .store import fingerprint
from .resources import slot

def final_frame(result,frame,check=lambda:None):
    from .render import sha,binary,command
    if type(frame)!=int or not 0<=frame<result['frames']:raise ValueError('frame outside final movie')
    path=Path(result['path'])
    if not path.is_file() or sha(path)!=result['sha256']:raise ValueError('final movie identity changed')
    executable=Path(binary('ffmpeg'))
    decoder={'binary':sha(executable),'libraries':{p.name:sha(p) for p in sorted(executable.parent.glob('*.dll'))},
             'operation':'select exact decoded frame, rgba PNG','version':1}
    key=fingerprint({'movie':result['sha256'],'frame':frame,'decoder':decoder})
    folder=path.parent/'review-frames';folder.mkdir(exist_ok=True)
    image=folder/(key+'.png');receipt=folder/(key+'.json')
    with slot('review-frame',check) as lease:
        if receipt.is_file():
            value=json.loads(receipt.read_text())
            if not image.is_file() or sha(image)!=value['sha256']:raise ValueError('review frame integrity check failed')
            return {**value,'cache_hit':True}
        pending=folder/(key+'.partial.png')
        try:
            command([executable,'-v','error','-nostdin','-y','-threads','2','-i',path,
                     '-vf',f'select=eq(n\\,{frame})','-frames:v','1','-pix_fmt','rgba',pending],lease.check)
            if not pending.is_file():raise ValueError('selected final frame unavailable')
            lease.check();os.replace(pending,image)
            value={'path':str(image),'sha256':sha(image),'frame':frame,'media_sha256':result['sha256'],
                   'decoder_hash':fingerprint(decoder),'evidence_kind':'final_encoded_frame','result_version':result.get('result_version',1)}
            temp=receipt.with_suffix('.partial');temp.write_text(json.dumps(value),encoding='utf8');os.replace(temp,receipt)
            return {**value,'cache_hit':False}
        finally:
            if pending.exists():pending.unlink()

def legacy_reference(result,frame):
    from .render import sha
    if result.get('result_version',1)!=1 or 'frame_hashes' not in result:raise ValueError('No legacy PNG reference in this result format')
    path=Path(result['path']).parent/'frames'/f'{frame:08d}.png'
    if not path.is_file() or sha(path)!=result['frame_hashes'].get(str(frame)):raise ValueError('legacy reference integrity check failed')
    return {'path':str(path),'sha256':sha(path),'frame':frame,'evidence_kind':'pre_encode_reference'}

def composition_reference(project,folder,frame,check=lambda:None):
    """Unbuilt preview only: decode at most one project-clock frame per source."""
    from .render import Rasterizer,binary,command,sha
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    with slot('composition-reference',check) as lease:
        raster=Rasterizer(project,folder,lease.check);raster.prepare(decode=False)
        for layer in project.layers:
            if not layer.start<=frame<layer.end:continue
            aid=layer.asset if layer.kind=='video' else layer.props.get('image') if layer.kind=='component' else None
            asset=raster.assets.get(aid)
            if not asset or asset.kind!='video':continue
            target=folder/('decode-'+layer.id);target.mkdir(exist_ok=True)
            out=target/f'{frame-layer.start:08d}.png'
            n=layer.source_start+frame-layer.start
            command([binary('ffmpeg'),'-v','error','-nostdin','-y','-threads','2','-i',asset.path,
                     '-vf',f'fps={project.fps.num}/{project.fps.den},trim=start_frame={n}:end_frame={n+1},setpts=PTS-STARTPTS',
                     '-frames:v','1',out],lease.check)
            if not out.is_file():raise ValueError('source too short for preview')
            raster.videos[layer.id]=target
        out=folder/f'reference-{frame}.png';raster.frame(frame).save(out)
        lease.check()
        return {'path':str(out),'sha256':sha(out),'frame':frame,'evidence_kind':'pre_encode_reference'}
