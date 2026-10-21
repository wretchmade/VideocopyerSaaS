import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator

SCHEMA = json.loads((Path(__file__).resolve().parents[3] / "docs/schemas/template-admission-v1.schema.json").read_text(encoding="utf-8-sig"))
VALIDATOR = Draft202012Validator(SCHEMA)
HASH_VERSION = "sorted-utf8-json-v1"
COMPILER_VERSION = "template-d-v1"


def implementation_hash():
    root = Path(__file__).resolve().parent
    sources = sorted(root.glob("*.py")) + [root.parents[1] / "local/templates.py"]
    return hashlib.sha256(b"".join(p.name.encode() + b"\0" + p.read_bytes() for p in sources) + canonical(SCHEMA).encode()).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf8")).hexdigest()


def issue(code, path, message, blocking=True, repair="修正该字段后使用新命令重新提交"):
    return dict(code=code, path=path, message=message, repair=repair, blocks_admission=blocking)


class TemplateError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__("; ".join(x["code"] + ": " + x["message"] for x in issues))


def fail(code, path, message):
    raise TemplateError([issue(code, path, message)])


def loads(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                fail("SCHEMA_INVALID", "/" + key, "重复 JSON 键")
            out[key] = value
        return out
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda x: fail("SCHEMA_INVALID", "", "不允许非有限数字"))
    except (ValueError, TypeError) as exc:
        if isinstance(exc, TemplateError):
            raise
        fail("SCHEMA_INVALID", "", "无法解析 JSON")


def schema_issues(envelope):
    return [issue("SCHEMA_INVALID", "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in e.absolute_path), e.message)
            for e in sorted(VALIDATOR.iter_errors(envelope), key=lambda e: str(list(e.absolute_path)))]
