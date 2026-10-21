"""Isolated non-paid browser fixture. Lifespan/Agent/Worker disabled."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = Path(os.environ["VC_TEMPLATE_FIXTURE"]).resolve()
if not work.is_relative_to((ROOT / ".local").resolve()) or work.exists():
    raise RuntimeError("A fresh isolated .local fixture directory is required")
work.mkdir(parents=True)
config = json.loads((ROOT / "config.local.json").read_text(encoding="utf-8-sig"))
for tool in ("ffmpeg", "ffprobe"):
    if os.environ.get("VC_TEMPLATE_" + tool.upper()):
        config[tool] = os.environ["VC_TEMPLATE_" + tool.upper()]
safe_config = {k: config.get(k) for k in ("font", "ffmpeg", "ffprobe")}
safe_config.update(port=int(os.environ["VC_TEMPLATE_PORT"]), data_dir=str(work / "data"), test_budget_cny=0,
                   media_profile="", planning={"model": "", "base_url": "", "max_output_tokens": 1})
cp = work / "config.json"
cp.write_text(json.dumps(safe_config), encoding="utf8")
os.environ.update(VC_CONFIG=str(cp), VC_DATA=str(work / "data"),
                  D_FFMPEG=config["ffmpeg"], D_FFPROBE=config["ffprobe"])
sys.path.insert(0, str(ROOT / "server"))
from local import templates, db
from PIL import Image
Image.new("RGB", (64, 64), "red").save(work / "product.png")
source_path = work / "source.mp4"
subprocess.run([config["ffmpeg"], "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                "color=c=navy:s=64x64:r=24:d=10", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source_path)],
               check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
env = json.loads((ROOT / "docs/examples/template-admission-v1.example.json").read_text(encoding="utf8"))
env.update(command_id="browser-synthetic-admission", producer_item_id="browser-synthetic-only")
env["candidate"]["catalog"]["title"] = "浏览器测试夹具（非制作样片）"
source = env["candidate"]["sources"][0]
media = templates.register_resource("source.mp4", source_path.read_bytes(), "video")
source["media_ref"] = {"resource_id": media["id"], "sha256": media["sha256"]}
analysis = templates.register_resource("analysis.json", json.dumps({"source_sha256": media["sha256"],
    "observations": source["observations"]}).encode(), "analysis")
source["analysis_ref"] = {"resource_id": analysis["id"], "sha256": analysis["sha256"]}
receipt = templates.admit(env)
if not receipt["accepted"]:
    raise RuntimeError(receipt)
from local.main import app
import uvicorn
(work / "ready.json").write_text(json.dumps(receipt), encoding="utf8")
uvicorn.run(app, host="127.0.0.1", port=safe_config["port"], lifespan="off", log_level="warning")
