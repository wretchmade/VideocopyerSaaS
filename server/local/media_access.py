"""Controlled visual input, never a filename masquerading as media understanding."""
import base64
from pathlib import Path
from . import db, commands
from .config import contained, DATA


def inspect_media(pid, args):
    from app.workbench_d.commercial.resources import slot,scoped_check
    with slot('visual-inspection',scoped_check(commands.engine(pid).store)) as lease:
        return _inspect_media(pid,args,lease.check)


def _inspect_media(pid,args,check):
    if bool(args.get("file_id")) == bool(args.get("build_id")):
        raise ValueError("指定一个 file_id 或 build_id")
    if args.get("file_id"):
        with db.transaction() as c:
            row = db.get(c, "file", args["file_id"], pid)
        if row["kind"] not in {"image","video"}:
            raise ValueError("视觉检查支持图片或视频；音频需通过 D 转写任务处理")
        path = contained(row["path"], DATA / "projects" / pid)
        from app.workbench_d.commercial.render import sha,binary,command
        if sha(path)!=row['sha256']:raise ValueError('素材哈希发生变化')
        if row['kind']=='video':
            frame=args.get('frame',0)
            if type(frame)!=int or frame<0:raise ValueError('需要有效的视频帧号')
            target=DATA/'projects'/pid/'inspection'/f"{row['sha256']}-{frame}.png"
            target.parent.mkdir(exist_ok=True)
            if not target.exists():
                import os
                pending=target.with_suffix('.partial.png')
                try:
                    command([binary('ffmpeg'),'-v','error','-nostdin','-y','-threads','2','-i',path,
                             '-vf',f"select=eq(n\\,{frame}),scale=1600:1600:force_original_aspect_ratio=decrease",
                             '-frames:v','1',pending],check,timeout=60)
                    if not pending.is_file():raise ValueError('帧号超出视频范围')
                    check();os.replace(pending,target)
                finally:
                    if pending.exists():pending.unlink()
            if not target.is_file():raise ValueError('帧号超出视频范围')
            path=target
    else:
        e = commands.engine(pid)
        build = e.store.build(args["build_id"])
        frame=args.get("frame",0)
        if build["status"]!="succeeded" or type(frame)!=int or not 0<=frame<build["spec"]["frames"]:
            raise ValueError("需要已完成的精确构建及有效帧号")
        from app.workbench_d.commercial.render_artifacts import final_frame
        from app.workbench_d.commercial.resources import scoped_check
        value=final_frame(build['result'],frame,scoped_check(e.store))
        path=contained(value['path'],DATA/'projects'/pid)
    from PIL import Image
    import io
    with Image.open(path) as im:
        im.thumbnail((1600, 1600))
        out = io.BytesIO()
        im.convert("RGB").save(out, format="JPEG", quality=85)
    check()
    return {"_contentItems": [{"type": "inputImage", "imageUrl": "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()}]}
