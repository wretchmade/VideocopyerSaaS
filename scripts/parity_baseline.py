"""Read-only inventory and verified rollback snapshot. Never submits D work."""
import hashlib
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from app.workbench_d.commercial.api import tools

PLUGIN = Path("C:/Users/Administrator/.codex/plugins/cache/personal/workbench-d/2.0.0-beta.1/skills/workbench-d")


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = ROOT / ".local" / "parity-backups" / stamp
    dest.mkdir(parents=True)
    manifest = {}
    for directory in ("server", "web", "scripts", "docs", "dist", ".local/data"):
        for path in (ROOT / directory).rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix in {".pyc"}:
                continue
            if path.name.endswith(("-wal", "-shm")) or path.suffix == ".lock":
                continue
            rel = path.relative_to(ROOT)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix in {".sqlite", ".sqlite3"}:
                with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(target) as out:
                    source.backup(out)
                    assert out.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            else:
                shutil.copy2(path, target)
                if sha(path) != sha(target):
                    raise RuntimeError(f"File changed during backup: {rel}")
            manifest[rel.as_posix()] = sha(target)
    for path in ROOT.iterdir():
        if path.is_file():
            shutil.copy2(path, dest / path.name)
            manifest[path.name] = sha(dest / path.name)
    shutil.copytree(PLUGIN, dest / "installed-skill")
    original = json.loads((PLUGIN / "references/tools.json").read_text(encoding="utf-8-sig"))
    current = tools()
    originals = {t["name"]: t for t in original}
    inventory = []
    for tool in current:
        name = tool["name"]
        inventory.append({"name": name, "baseline": "original" if name in originals else "brand-extension",
                          "schema_equal": tool == originals.get(name), "status": "pending",
                          "adapter": "project-scoped registry", "test": "tests/test_parity.py::test_catalog_contracts"})
    builds = []
    for path in (dest / ".local/data").rglob("state.sqlite"):
        with sqlite3.connect(path) as c:
            for bid, status, identity in c.execute("SELECT id,status,identity FROM builds"):
                builds.append({"database": str(path.relative_to(dest)), "id": bid, "status": status,
                               "identity": json.loads(identity)})
    cfg = json.loads((ROOT / "config.local.json").read_text(encoding="utf-8-sig"))
    evidence = {"created": stamp, "backup": str(dest), "files": len(manifest),
                "original_tools": len(original), "migrated_tools": len(current),
                "planning_model": cfg.get("planning", {}).get("model"),
                "commercial_sha256": hashlib.sha256(b"".join(p.read_bytes() for p in sorted((ROOT / "server/app/workbench_d/commercial").iterdir()) if p.suffix in {".py", ".mjs"})).hexdigest(),
                "builds": builds, "tools": inventory,
                "backup_consistency": "SQLite online backups; cross-store snapshot is not atomic. Preserve receipts and never replay unknown requests.",
                "legacy_runtime": "Full original server snapshot retained. Do not mutate commercial while active legacy builds exist."}
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf8")
    out = ROOT / "docs/evidence/parity"
    out.mkdir(parents=True, exist_ok=True)
    (out / "baseline.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf8")
    (out / "installed-tools.json").write_text(json.dumps(original, ensure_ascii=False, indent=2), encoding="utf8")
    (out / "migrated-tools.json").write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({k: v for k, v in evidence.items() if k not in {"builds", "tools"}}, ensure_ascii=False))
    print("active builds:", sum(b["status"] in {"queued", "running"} for b in builds))


if __name__ == "__main__":
    main()
