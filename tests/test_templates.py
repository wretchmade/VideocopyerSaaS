"""Non-paid acceptance tests. Generated fixtures are NOT publication evidence."""
import copy
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("VC_DATA", tempfile.mkdtemp(prefix="vc-templates-"))
sys.path.insert(0, str(ROOT / "server"))
from local import db, projects, templates, commands
from app.creative_templates.contracts import TemplateError, digest, loads
from app.creative_templates.admission import validate
from app.creative_templates.expansion import expand
from app.creative_templates.compiler import adapt, compile_document
from app.workbench_d.commercial.engine import Engine


def example():
    return json.loads((ROOT / "docs/examples/template-admission-v1.example.json").read_text(encoding="utf8"))


def png(color="red"):
    out = io.BytesIO()
    Image.new("RGB", (32, 32), color).save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def candidate():
    env = example()
    env.update(command_id=db.uid(), producer_item_id=db.uid())
    source = env["candidate"]["sources"][0]
    # Admission unit fixture uses honest synthetic bytes with a fake probe record.
    # Resource decoding itself is tested separately; this is never a live catalog fixture.
    for key, kind, data in (("media_ref", "video", b"synthetic-video-fixture"),
                            ("analysis_ref", "analysis", b"synthetic-analysis-fixture")):
        rid = db.uid()
        path = templates.DATA / ("test-resource-" + rid)
        path.write_bytes(data)
        row = {"id": rid, "path": str(path), "sha256": templates.sha(path), "kind": kind, "scope": "research",
               "duration_ms": 10000, "source_sha256": source["media_ref"]["sha256"], "observations": source["observations"]}
        with db.transaction() as c:
            db.put(c, "template_resource", rid, row)
        source[key] = {"resource_id": rid, "sha256": row["sha256"]}
    return env


@pytest.fixture
def admitted(candidate):
    receipt = templates.admit(candidate)
    assert receipt["accepted"], receipt
    return candidate, receipt


@pytest.fixture
def mounted(admitted):
    env, r = admitted
    cid = db.uid()
    f = templates.stage_file(cid, "product.png", png())
    value = {k: r[k] for k in ("template_id", "revision", "content_hash")}
    value.update(bindings={"product": [f["id"]]})
    draft = templates.save_composer(cid, {"expected_revision": 0, "template_mount": value})
    body = {"command_id": db.uid(), "composer_id": cid, "expected_composer_revision": draft["revision"]}
    sent = templates.send(body)
    yield sent["project"], sent["template_instance"], cid, body
    # Test-created quote reservations must not contaminate legacy global budget tests.
    with db.transaction() as c:
        for usage in db.all(c, "usage", sent["project"]):
            usage["state"] = "released"
            db.put(c, "usage", usage["id"], usage, sent["project"], True)


@pytest.fixture
def route(monkeypatch):
    value = {"provider": "ark", "model": "seedance-2", "max_inputs": 3, "roles": ["first_frame", "reference_image"],
             "min_seconds": 1, "max_seconds": 15, "max_cost_micros": 33000000, "options": {"resolution": "720p", "generate_audio": False}}
    monkeypatch.setitem(templates.CONFIG, "template_routes", {"reference_guided_video_v1": value})
    return value


def test_baseline_hashes_and_demo_rejected():
    expected = ["CCB817194A7E553B321B88DBBA7EC9C19A232404C2B9FC884CFD707AE3EB3EF8",
                "9F693B57D0921D11F4F437CC57F9904C562921191CC1253C720EDB1CA6A8BA2C",
                "93765CFF4CA0BD9D4837D3BB14CC529BEC0074B258EA8F1E92A38682A8DA35CA"]
    for name, h in zip(["TEMPLATE-EXPANSION-PLAN.md", "template-admission-v1.schema.json", "template-admission-v1.example.json"], expected):
        assert templates.sha(ROOT / "docs/evidence/template-baseline-20261020" / name).upper() == h
    result = templates.check(example())
    assert not result["accepted"]
    assert len([x for x in result["issues"] if x["code"] == "ASSET_NOT_FOUND"]) == 2


@pytest.mark.parametrize("mutation,code", [
    (lambda e: e["candidate"]["catalog"].pop("title"), "SCHEMA_INVALID"),
    (lambda e: e["candidate"].update(published=True), "SCHEMA_INVALID"),
    (lambda e: e["candidate"]["sources"][0]["media_ref"].update(sha256="f" * 64), "ASSET_HASH_MISMATCH"),
    (lambda e: e["candidate"]["nodes"][0]["depends_on"].append({"node_id": "render", "binding": "all_instances"}), "GRAPH_CYCLE"),
    (lambda e: e["candidate"]["prompt_recipes"][0]["sections"].update(identity="{{identity.missing}}"), "VARIABLE_UNBOUND"),
    (lambda e: e["candidate"]["sources"][0]["observations"][0].update(range_ms=[0, 10001]), "SOURCE_RANGE_INVALID"),
    (lambda e: e["candidate"]["nodes"][3].update(parameter_inputs=[]), "CAPABILITY_CONTRACT_MISMATCH"),
    (lambda e: e["candidate"]["nodes"][3]["depends_on"][0].update(binding="same_instance"), "DEPENDENCY_BINDING_INVALID"),
    (lambda e: e["candidate"]["checks"][0].update(method_id="made_up"), "CHECK_UNREGISTERED"),
    (lambda e: e["candidate"]["components"][0]["recipe_overrides"][0].update(text="{{params.undeclared}}"), "VARIABLE_UNBOUND"),
])
def test_field_errors(candidate, mutation, code):
    mutation(candidate)
    result = templates.check(candidate)
    assert any(p["code"] == code and p["path"].startswith("/") for p in result["issues"]), result


def test_json_rejects_duplicates_nonfinite():
    for raw in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
        with pytest.raises(TemplateError):
            loads(raw)
    assert digest({"a": 1, "b": [1, 2]}) == digest({"b": [1, 2], "a": 1})
    assert digest([1, 2]) != digest([2, 1])


def test_agent_receives_exact_occurrences_and_bounded_repair(mounted):
    pid, iid, _, _ = mounted
    inst = templates.instance(pid, iid)
    assert inst["expanded"]["playback"][0]["occurrence_id"] == "hook_1"
    proposal = {"segment_text": {"guessed_id": "bad"}}
    for i in range(3):
        command = "bad-adaptation-" + db.uid()
        for retry in range(2):
            with pytest.raises(TemplateError, match="hook_1"):
                templates.propose(pid, iid, proposal, command)
    with pytest.raises(TemplateError, match="PLAN_REPAIR_LIMIT"):
        templates.propose(pid, iid, {}, db.uid())
    with db.transaction() as c:
        assert len(db.all(c, "template_adaptation_attempt", pid)) == 3


def test_idempotency_versions_and_concurrency(admitted):
    env, r = admitted
    assert templates.admit(env) == r
    changed = copy.deepcopy(env)
    changed["candidate"]["catalog"]["title"] = "new"
    with pytest.raises(TemplateError, match="IDEMPOTENCY_CONFLICT"):
        templates.admit(changed)
    changed.update(command_id=db.uid(), expected_revision=1)
    other = copy.deepcopy(changed)
    other["command_id"] = db.uid()
    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(templates.admit, [changed, other]))
    assert sum(r["accepted"] for r in replies) == 1
    assert templates.get_revision(r["template_id"], 1)["candidate"] == env["candidate"]
    assert templates.get_revision(r["template_id"], 2)["candidate"]["catalog"]["title"] == "new"


def test_allocation_all_lengths_stable_identity():
    c = example()["candidate"]
    a = expand(c, {"output": {"duration_seconds": 10}})
    b = expand(c, {"output": {"duration_seconds": 20}}, a["playback"])
    assert len(a["playback"]) < len(b["playback"])
    assert {n["id"] for n in a["graph"]} <= {n["id"] for n in b["graph"]}
    for seconds in range(7, 25):
        out = expand(c, {"output": {"duration_seconds": seconds}})
        assert sum(x["frames"] for x in out["playback"]) == seconds * 24
        assert out["playback"][0]["segment_id"] == "hook" and out["playback"][-1]["segment_id"] == "hero"
        assert out["model_calls"] == 0 and all("state" not in n for n in out["graph"])
    for seconds in (6, 25):
        with pytest.raises(TemplateError, match="DURATION_UNSATISFIABLE"):
            expand(c, {"output": {"duration_seconds": seconds}})
    rational = copy.deepcopy(c)
    rational["output_policy"]["fps"] = {"num": 30000, "den": 1001}
    assert expand(rational)["frames"] == 300


def test_resource_registration_and_invalid_bytes():
    r = templates.register_resource("product.png", png(), "image")
    assert templates.register_resource("product.png", png(), "image")["id"] == r["id"]
    assert "path" not in r
    with pytest.raises(Exception):
        templates.register_resource("not.png", b"not an image", "image")
    with pytest.raises(TemplateError):
        templates.register_resource("analysis.json", b'{"a":1,"a":2}', "analysis")


def test_draft_not_published_or_auto(admitted):
    _, r = admitted
    assert any(t["template_id"] == r["template_id"] for t in templates.catalog(True))
    assert not any(t["template_id"] == r["template_id"] for t in templates.catalog())
    assert templates.preview(r["template_id"], 1, {})["model_calls"] == 0
    for tier in ("assisted", "automatic"):
        with pytest.raises(TemplateError):
            templates.lifecycle(r["template_id"], 1, "publish", {"command_id": db.uid(), "tier": tier})


def test_atomic_send_refresh_restart_duplicate_and_rollback(mounted):
    pid, key, cid, body = mounted
    repeated = templates.send(body)
    assert repeated["project"] == pid and repeated["template_instance"] == key
    draft = templates.get_composer(cid)
    assert draft["project"] == pid and draft["sent_instance"] == key
    with db.transaction() as c:
        assert len(db.all(c, "message", pid)) == 1
        inbox = db.get(c, "agent_inbox", repeated["run_id"], pid)
        assert inbox["template_instance"] == key
        assert db.get(c, "message", inbox["message_id"], pid)["template_instance"] == key
        before = len(db.all(c, "project"))
    badcid = db.uid()
    value = {**templates.instance(pid, key)["template"], "bindings": {"product": ["missing"]}}
    templates.save_composer(badcid, {"expected_revision": 0, "template_mount": value})
    with pytest.raises(TemplateError, match="ASSET_NOT_FOUND"):
        templates.send({"command_id": db.uid(), "composer_id": badcid, "expected_composer_revision": 1})
    with db.transaction() as c:
        assert len(db.all(c, "project")) == before
    assert templates.instance(pid, key)["instance_revision"] == 1


def plan_for(pid, key, text=""):
    return templates.propose(pid, key, {"identity": {"product": "红色产品"}, "parameters": {"end_copy": text}}, db.uid())


def test_compile_receipt_recovery_and_node_cache(mounted, route, monkeypatch):
    pid, key, _, _ = mounted
    p1 = plan_for(pid, key)
    original = commands.bind
    monkeypatch.setattr(commands, "bind", lambda *args: (_ for _ in ()).throw(RuntimeError("crash after D")))
    with pytest.raises(RuntimeError):
        templates.compile_plan(pid, p1["id"])
    e = commands.engine(pid)
    with e.store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
    monkeypatch.setattr(commands, "bind", original)
    r1 = templates.compile_plan(pid, p1["id"])
    with e.store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
    assert templates.compile_plan(pid, p1["id"]) == r1
    doc1 = e.store.project(r1["native"]["projectId"])["document"]
    p2 = plan_for(pid, key, "全新片尾")
    r2 = templates.compile_plan(pid, p2["id"])
    doc2 = e.store.project(r2["native"]["projectId"])["document"]
    assert commands.task_keys(doc1, {}) == commands.task_keys(doc2, {})
    assert doc1["layers"] != doc2["layers"]


def test_three_execution_gates_direct_edit(mounted, route, monkeypatch):
    pid, key, _, _ = mounted
    with pytest.raises(TemplateError, match="TEMPLATE_VALIDATION_REQUIRED"):
        commands.prepare(pid)
    plan = plan_for(pid, key)
    result = templates.compile_plan(pid, plan["id"])
    e = commands.engine(pid)
    monkeypatch.setattr(commands, "runtime", lambda doc: {})
    monkeypatch.setattr(Engine, "check", lambda *a: {"executable": True})
    monkeypatch.setattr("app.workbench_d.commercial.providers.quote_task", lambda task: {
        "ready": True, "currency": "CNY", "maximumReservedMicros": task["max_cost_micros"],
        "quote": {"upperMicros": 1, "expires": 9999999999}, "account": "unit-test"})
    monkeypatch.setitem(templates.CONFIG, "test_budget_cny", 1000000)
    q = commands.prepare(pid)
    task = commands.confirm(pid, q["id"], db.uid())
    source = e.store.project(result["native"]["projectId"])
    doc = copy.deepcopy(source["document"])
    doc["layers"][0]["x"] = 1
    commands.dispatch(pid, "d_edit_project", {"commandId": db.uid(), "projectId": source["projectId"], "baseRevision": source["authorRevision"], "document": doc})
    with pytest.raises(TemplateError, match="TEMPLATE_VALIDATION_REQUIRED"):
        commands.prepare(pid)
    with pytest.raises(TemplateError, match="TEMPLATE_VALIDATION_REQUIRED"):
        commands.tick_native(task)
    # A queued stale task never acquired a build or provider request.
    with db.transaction() as c:
        assert not db.get(c, "task", task["id"], pid)["build_id"]


def test_retire_keeps_instance_and_history(mounted):
    pid, key, cid, _ = mounted
    inst = templates.instance(pid, key)
    templates.lifecycle(inst["template"]["template_id"], 1, "retire", {"command_id": db.uid()})
    assert templates.instance(pid, key)["template_revision"]["state"] == "retired"
    with pytest.raises(TemplateError, match="TEMPLATE_UNAVAILABLE"):
        templates.send({"command_id": db.uid(), "text": "继续"}, pid)


def test_model_reference_capacity_not_silently_dropped(mounted, route):
    pid, key, _, _ = mounted
    inst = templates.instance(pid, key)
    candidate = inst["template_revision"]["candidate"]
    plan = adapt(candidate, inst, {"identity": {"product": "red"}})
    with db.transaction() as c:
        files = templates.validate_bindings(c, candidate, plan["expanded"]["options"], pid)
    route["roles"] = ["reference_image"]
    with pytest.raises(TemplateError, match="REFERENCE_CAPACITY_EXCEEDED"):
        compile_document(candidate, plan, files, templates.routes())


def test_agent_cannot_modify_structure_or_publish(mounted):
    pid, key, _, _ = mounted
    for proposal in ({"document": {}}, {"parameters": {"provider": "other"}}, {"segment_text": {"made-up": "text"}}):
        with pytest.raises(TemplateError):
            templates.propose(pid, key, proposal, db.uid())
    from local.tool_registry import names
    assert not any("publish" in name and "template" in name for name in names())


def test_template_api_strict_json_csrf_and_preview(admitted):
    from local.main import app, CSRF
    from fastapi.testclient import TestClient
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    env, r = admitted
    assert client.post("/api/template-admissions", json=env).status_code == 403
    headers = {"x-vc-token": CSRF}
    bad = client.post("/api/template-admissions", content='{"command_id":"a","command_id":"b"}', headers=headers)
    assert bad.status_code == 409 and bad.json()["issues"][0]["code"] == "SCHEMA_INVALID"
    out = client.post(f"/api/templates/{r['template_id']}/revisions/1/preview", json={}, headers=headers)
    assert out.status_code == 200 and out.json()["model_calls"] == 0
    assert client.get("/api/templates").json() == []


def test_stop_message_keeps_exact_instance(mounted):
    pid, key, cid, _ = mounted
    sent = templates.send({"command_id": db.uid(), "text": "停止制作"}, pid)
    assert sent["template_instance"] == key
    with db.transaction() as c:
        assert len(db.all(c, "template_instance", pid)) == 1
        assert db.get(c, "agent_inbox", sent["run_id"], pid)["intent"] == {"op": "stop"}


def test_feature_switch_preserves_authorized_gate(mounted, route, monkeypatch):
    pid, key, _, _ = mounted
    r = templates.compile_plan(pid, plan_for(pid, key)["id"])
    source = commands.engine(pid).store.project(r["native"]["projectId"])
    with db.transaction() as c:
        binding = templates.gate(c, pid, source)
    monkeypatch.setitem(templates.CONFIG, "templates_enabled", False)
    with pytest.raises(TemplateError, match="FEATURE_DISABLED"):
        templates.send({"command_id": db.uid(), "text": "继续"}, pid)
    with db.transaction() as c:
        assert templates.gate(c, pid, source, binding, authorized=True) == binding
    assert templates.instance(pid, key)["id"] == key


def test_product_and_person_slots_and_multiple_details(mounted, route):
    pid, key, _, _ = mounted
    inst = templates.instance(pid, key)
    c = copy.deepcopy(inst["template_revision"]["candidate"])
    person = projects.add_file(pid, "person.png", png("blue"))
    c["input_slots"].append({**c["input_slots"][0], "id": "person", "identity_kind": "person", "max_items": 1})
    c["prompt_recipes"][0]["variables"].append("identity.person")
    c["prompt_recipes"][0]["sections"]["identity"] += " 人物：{{identity.person}}。"
    for node in c["nodes"]:
        if node["kind"] == "generate":
            node["slot_inputs"].append({"slot_id": "person", "role": "reference_image", "selection": "all"})
    inst["options"]["bindings"]["person"] = [person["id"]]
    plan = adapt(c, inst, {"identity": {"product": "red", "person": "blue"}})
    with db.transaction() as conn:
        files = templates.validate_bindings(conn, c, plan["expanded"]["options"], pid)
    doc, _ = compile_document(c, plan, files, templates.routes())
    assert all(t["input_roles"] == ["first_frame", "reference_image"] for t in doc["tasks"])
    assert all("blue" in t["prompt"] and len(t["inputs"]) == 2 for t in doc["tasks"])
    # Three detail images consume exactly three inputs, never just the first.
    c = inst["template_revision"]["candidate"]
    inst["options"]["bindings"].pop("person")
    inst["options"]["bindings"]["product"] += [person["id"], projects.add_file(pid, "detail.png", png("green"))["id"]]
    plan = adapt(c, inst, {"identity": {"product": "product details"}})
    with db.transaction() as conn:
        files = templates.validate_bindings(conn, c, plan["expanded"]["options"], pid)
    doc, _ = compile_document(c, plan, files, templates.routes())
    assert all(len(t["inputs"]) == 3 for t in doc["tasks"])
    route["max_inputs"] = 2
    with pytest.raises(TemplateError, match="REFERENCE_CAPACITY_EXCEEDED"):
        compile_document(c, plan, files, templates.routes())


def test_new_product_invalidates_generation_and_old_instance_stays(mounted, route):
    pid, key, cid, _ = mounted
    first = templates.compile_plan(pid, plan_for(pid, key)["id"])
    e = commands.engine(pid)
    doc1 = e.store.project(first["native"]["projectId"])["document"]
    inst = templates.instance(pid, key)
    new = projects.add_file(pid, "different-product.png", png("green"))
    changed = {**inst["template"], **inst["options"], "bindings": {"product": [new["id"]]}}
    sent = templates.send({"command_id": db.uid(), "template_mount": changed, "text": "换产品"}, pid)
    second = templates.compile_plan(pid, plan_for(pid, sent["template_instance"])["id"])
    doc2 = e.store.project(second["native"]["projectId"])["document"]
    keys1, keys2 = commands.task_keys(doc1, {}), commands.task_keys(doc2, {})
    assert keys1.keys() == keys2.keys()
    assert all(keys1[n] != keys2[n] for n in keys1)
    assert templates.instance(pid, key)["options"]["bindings"] != changed["bindings"]


def test_material_change_invalidates_original_binding(mounted, route):
    pid, key, _, _ = mounted
    result = templates.compile_plan(pid, plan_for(pid, key)["id"])
    source = commands.engine(pid).store.project(result["native"]["projectId"])
    with db.transaction() as c:
        report = templates.gate(c, pid, source)
        fid = next(iter(db.get(c, "template_instance", key, pid)["binding_hashes"]))
        file = db.get(c, "file", fid, pid)
    Path(file["path"]).write_bytes(png("yellow"))
    with db.transaction() as c, pytest.raises(TemplateError, match="ASSET_HASH_MISMATCH"):
        templates.gate(c, pid, source, report)


def test_inbox_recovery_retains_exact_reference(mounted):
    from local import coordinator
    pid, key, _, body = mounted
    sent = templates.send(body)
    with db.transaction() as c:
        item = db.get(c, "agent_inbox", sent["run_id"], pid)
        item["status"] = "dispatching"
        db.put(c, "agent_inbox", item["id"], item, pid, True)
    coordinator.recover()
    with db.transaction() as c:
        item = db.get(c, "agent_inbox", sent["run_id"], pid)
        assert item["status"] == "needs_attention" and item["template_instance"] == key


def test_multistage_compilation_is_explicitly_blocked(mounted, route):
    pid, key, _, _ = mounted
    inst = templates.instance(pid, key)
    c = inst["template_revision"]["candidate"]
    plan = adapt(c, inst, {"identity": {"product": "red"}})
    c["nodes"][1]["output_inputs"] = [{"node_id": "hook_video", "binding": "all_instances", "role": "reference_video"}]
    with pytest.raises(TemplateError, match="STAGE_AUTHORIZATION_REQUIRED"):
        compile_document(c, plan, {}, templates.routes())


def test_cleanup_never_deletes_bound_or_mounted_uploads(mounted):
    pid, key, cid, _ = mounted
    orphan = templates.stage_file(cid, "orphan.png", png("white"))
    with db.transaction() as c:
        for row in db.all(c, "template_staged", cid):
            row["created"] = 1
            db.put(c, "template_staged", row["id"], row, cid, True)
        bound_id = next(iter(db.get(c, "template_instance", key, pid)["binding_hashes"]))
        bound_path = db.get(c, "file", bound_id, pid)["path"]
    cleaned = templates.cleanup_staged()
    assert orphan["id"] in cleaned["removed"] and bound_id not in cleaned["removed"]
    assert Path(bound_path).is_file()
