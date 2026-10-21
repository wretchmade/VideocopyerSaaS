"""Screenshot / interaction recording adapter; no inherited browser state."""
import json, os, shutil
from pathlib import Path
from .render import command, binary, sha
from .resources import operation


@operation('browser-capture')
def capture(spec, folder, check=lambda:None):
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    request=folder/'request.json';request.write_text(spec.model_dump_json(),encoding='utf8')
    node=os.environ.get('D_NODE') or shutil.which('node')
    if not node: raise ValueError('Node is required for web capture')
    command([node,Path(__file__).with_name('browser.mjs'),request,folder],check,timeout=max(60,spec.frames*3+spec.timeout_ms/1000))
    evidence=json.loads((folder/'capture.json').read_text())
    if evidence['blocked']: raise ValueError('page requested undeclared resource origins; add allowed_origins explicitly')
    if spec.frames==1: output=folder/'00000000.png';kind='image'
    else:
        output=folder/'capture.mov';kind='video'
        command([binary('ffmpeg'),'-v','error','-nostdin','-y','-framerate',f'{spec.fps.num}/{spec.fps.den}',
            '-i',folder/'%08d.png','-frames:v',str(spec.frames),'-c:v','png','-pix_fmt','rgba',output],check)
    return dict(path=str(output),sha256=sha(output),kind=kind,evidence=evidence)
