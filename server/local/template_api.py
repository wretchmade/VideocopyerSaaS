"""Local operator routes; protected by the application's host/origin/token middleware."""
import asyncio
from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import FileResponse
from . import templates, db
from app.creative_templates.contracts import loads, fail

router = APIRouter()


async def body(request):
    raw = await request.body()
    if len(raw) > 2 * 1024 * 1024:
        fail("CAPACITY_EXCEEDED", "", "JSON 请求超过 2 MB")
    value = loads(raw)
    if not isinstance(value, dict):
        fail("SCHEMA_INVALID", "", "请求必须是 JSON 对象")
    return value


@router.post("/api/template-resources")
async def resource(file: UploadFile = File(...), kind: str = Form(...), scope: str = Form("research")):
    data = await file.read(100 * 1024 * 1024 + 1)
    return await asyncio.to_thread(templates.register_resource, file.filename or "file", data, kind, scope)


@router.post("/api/template-admissions/validate")
async def validate(request: Request):
    return await asyncio.to_thread(templates.check, await body(request))


@router.post("/api/template-admissions")
async def admit(request: Request):
    return await asyncio.to_thread(templates.admit, await body(request))


@router.get("/api/templates")
def catalog(author: bool = False):
    return templates.catalog(author)


@router.get("/api/templates/{tid}/revisions/{rev}")
def revision(tid: str, rev: int):
    return templates.get_revision(tid, rev)


@router.get("/api/templates/{tid}/revisions/{rev}/sample")
def sample(tid: str, rev: int):
    row = templates.get_revision(tid, rev)
    sample = row.get("sample")
    if not sample:
        fail("PUBLICATION_EVIDENCE_MISSING", "", "此版本尚无系统生成样片")
    with db.transaction() as c:
        d = db.get(c, "delivery", sample["delivery_id"], sample["project"])
    from pathlib import Path
    from app.workbench_d.commercial.render import sha
    path = Path(d["preview_path"])
    if sha(path) != sample["sha256"]:
        fail("ASSET_HASH_MISMATCH", "", "样片完整性检查失败")
    return FileResponse(path, media_type="video/mp4")


@router.post("/api/templates/{tid}/revisions/{rev}/preview")
async def preview(tid: str, rev: int, request: Request):
    return await asyncio.to_thread(templates.preview, tid, rev, await body(request))


@router.post("/api/templates/{tid}/revisions/{rev}/{action}")
async def lifecycle(tid: str, rev: int, action: str, request: Request):
    return await asyncio.to_thread(templates.lifecycle, tid, rev, action, await body(request))


@router.get("/api/template-composers/{cid}")
def composer(cid: str):
    return templates.get_composer(cid)


@router.put("/api/template-composers/{cid}")
async def save(cid: str, request: Request):
    return await asyncio.to_thread(templates.save_composer, cid, await body(request))


@router.post("/api/template-composers/{cid}/files")
async def upload(cid: str, file: UploadFile = File(...)):
    return await asyncio.to_thread(templates.stage_file, cid, file.filename or "file", await file.read(100 * 1024 * 1024 + 1))


@router.post("/api/template-messages")
async def send(request: Request):
    return await asyncio.to_thread(templates.send, await body(request))


@router.get("/api/projects/{pid}/template-instances/{key}")
def instance(pid: str, key: str):
    return templates.instance(pid, key)


@router.post("/api/projects/{pid}/template-detach")
async def detach(pid: str, request: Request):
    return templates.detach(pid, await body(request))


@router.post("/api/projects/{pid}/template-runs/{task_id}/review")
async def review(pid: str, task_id: str, request: Request):
    return templates.review_run(pid, task_id, await body(request))
