"""Restricted adaptation and deterministic D document construction."""
import copy
import math
from .contracts import fail, digest, COMPILER_VERSION
from .admission import TOKEN
from .expansion import expand
from .registry import CAPABILITIES, readiness


def adapt(candidate, instance, proposal, previous=None):
    if not isinstance(proposal, dict) or set(proposal) - {"identity", "parameters", "segment_text"}:
        fail("ADAPTATION_OUT_OF_SCOPE", "/adaptation", "只允许身份描述、声明参数与片段说明")
    identity = proposal.get("identity", {})
    if not isinstance(identity, dict) or set(identity) - {s["id"] for s in candidate["input_slots"]}:
        fail("ADAPTATION_OUT_OF_SCOPE", "/adaptation/identity", "未知身份槽")
    for key, value in identity.items():
        if not isinstance(value, str) or not 1 <= len(value) <= 2000:
            fail("SCHEMA_INVALID", "/adaptation/identity/" + key, "身份描述需为 1～2000 字符")
    opts = copy.deepcopy(instance["options"])
    parameters = proposal.get("parameters", {})
    if not isinstance(parameters, dict) or set(parameters) - set(candidate["adaptation_policy"]["editable_parameter_ids"]):
        fail("ADAPTATION_OUT_OF_SCOPE", "/adaptation/parameters", "参数不在可编辑范围")
    opts["parameters"].update(parameters)
    expanded = expand(candidate, opts, previous)
    texts = proposal.get("segment_text", {})
    if not isinstance(texts, dict) or set(texts) - {o["occurrence_id"] for o in expanded["playback"]}:
        fail("ADAPTATION_OUT_OF_SCOPE", "/adaptation/segment_text",
             "片段不存在；可省略 segment_text。有效 occurrence ID：" +
             ", ".join(o["occurrence_id"] for o in expanded["playback"]))
    if any(not isinstance(t, str) or len(t) > 2000 for t in texts.values()):
        fail("SCHEMA_INVALID", "/adaptation/segment_text", "片段描述超过范围")
    if texts and not candidate["adaptation_policy"]["allow_free_text"]:
        fail("ADAPTATION_OUT_OF_SCOPE", "/adaptation/segment_text", "模板禁止自由描述")
    return {"adaptation": proposal, "expanded": expanded, "compiler_version": COMPILER_VERSION}


def compile_document(candidate, plan, files, routes, font=None):
    blocking = readiness(candidate, routes)
    if blocking:
        from .contracts import TemplateError
        raise TemplateError(blocking)
    x = plan["expanded"]
    opts = x["options"]
    width, height = {"9:16": (540, 960), "16:9": (960, 540), "1:1": (720, 720)}[opts["output"]["aspect_ratio"]]
    doc = {"width": width, "height": height, "fps": x["fps"], "frames": x["frames"],
           "assets": [], "tasks": [], "layers": [], "audio": [], "transitions": []}
    used = {}
    def asset(fid):
        f = files[fid]
        aid = "a_" + digest(fid)[:24]
        if aid not in used:
            used[aid] = True
            doc["assets"].append({"id": aid, "kind": f["kind"], "path": f["path"], "sha256": f["sha256"],
                                  "source": "file:" + fid, "license": "user supplied; scoped template instance"})
        return aid
    recipes = {r["id"]: r for r in candidate["prompt_recipes"]}
    nodes = {n["id"]: n for n in candidate["nodes"]}
    components = {r["id"]: r for r in candidate["components"]}
    mapped = []
    for row in x["graph"]:
        n = nodes[row["template_node_id"]]
        if n["kind"] != "generate":
            continue
        if n["scope"] != "per_segment" or n["output_inputs"]:
            fail("STAGE_AUTHORIZATION_REQUIRED", "/nodes/" + n["id"], "首版编译只支持独立单阶段片段生成")
        occ = next(o for o in x["playback"] if o["occurrence_id"] == row["occurrence_id"])
        cap = CAPABILITIES[n["capability_id"]]
        route = routes[cap["route"]]
        inputs, roles = [], []
        for binding in n["slot_inputs"]:
            fids = opts["bindings"].get(binding["slot_id"], [])
            selected = fids[:1] if binding["selection"] == "first" else fids[1:] if binding["selection"] == "remaining" else fids
            for fid in selected:
                inputs.append(asset(fid))
                roles.append(binding["role"])
        allowed_roles = route.get("roles", [])
        if set(roles) - set(allowed_roles) or len(inputs) > min(cap["max_inputs"], route.get("max_inputs", 0)):
            fail("REFERENCE_CAPACITY_EXCEEDED", "/nodes/" + n["id"] + "/slot_inputs", "配置模型不支持此参考数量或角色；未静默丢图")
        if any(roles.count(role) > limit for role, limit in cap["max_role"].items()):
            fail("REFERENCE_CAPACITY_EXCEEDED", "/nodes/" + n["id"], "参考角色数量超限")
        if route.get("exclusive_frame_reference") and "first_frame" in roles and "reference_image" in roles:
            fail("REFERENCE_CAPACITY_EXCEEDED", "/nodes/" + n["id"], "该路线禁止首帧与参考图混用")
        sections = copy.deepcopy(recipes[n["prompt_recipe_id"]]["sections"])
        for cid in opts["component_selections"].values():
            comp = components[cid]
            if n["segment_id"] in comp["target_segment_ids"]:
                for override in comp["recipe_overrides"]:
                    if override["recipe_id"] == n["prompt_recipe_id"]:
                        sections[override["section"]] = override["text"]
        variables = {"segment.purpose": occ["purpose"], "segment.label": occ["label"],
                     **{"params." + k: v for k, v in opts["parameters"].items()},
                     **{"output." + k: str(v) for k, v in opts["output"].items()},
                     **{"components." + k: v for k, v in opts["component_selections"].items()}}
        for slot in candidate["input_slots"]:
            key = slot["id"]
            if opts["bindings"].get(key):
                description = plan["adaptation"].get("identity", {}).get(key)
                if not description:
                    fail("VARIABLE_UNBOUND", "/adaptation/identity/" + key, "需要与绑定参考图一致的身份描述")
                variables["identity." + key] = description
        def substitute(match):
            if match[1] not in variables:
                fail("VARIABLE_UNBOUND", "/prompt", "变量没有已绑定值：" + match[1])
            return variables[match[1]]
        prompt = "\n".join(TOKEN.sub(substitute, sections[k]) for k in ("identity", "creative", "environment", "motion", "constraints"))
        text = plan["adaptation"].get("segment_text", {}).get(occ["occurrence_id"])
        if text:
            prompt += "\n本段补充（固定要求仍须满足）：" + text
        seconds = math.ceil(occ["frames"] * x["fps"]["den"] / x["fps"]["num"])
        if not route.get("min_seconds", 1) <= seconds <= route.get("max_seconds", 0):
            fail("CAPABILITY_UNAVAILABLE", "/nodes/" + n["id"], "路线不支持展开后的片段时长")
        options = {**route.get("options", {}), "duration": seconds, "ratio": opts["output"]["aspect_ratio"]}
        task = {"id": row["id"], "kind": "generation", "provider": route["provider"], "model": route["model"],
                "prompt": prompt, "inputs": inputs, "input_roles": roles, "output_kind": "video", "depends_on": [],
                "options": options, "max_cost_micros": route["max_cost_micros"]}
        doc["tasks"].append(task)
        mapped.append({"template_node": n["id"], "occurrence_id": occ["occurrence_id"], "d_node": row["id"],
                       "requirement_ids": occ["requirement_ids"]})
    # Every playback occurrence has exactly one video producer in this compiler version.
    for occ in x["playback"]:
        sources = [m for m in mapped if m["occurrence_id"] == occ["occurrence_id"]]
        if len(sources) != 1:
            fail("COMPILER_UNSUPPORTED", "/segments/" + occ["segment_id"], "首版要求每个播放段恰有一个画面产物")
        doc["layers"].append({"id": "l_" + digest(occ["occurrence_id"])[:24], "kind": "video",
                              "asset": sources[0]["d_node"], "start": occ["start"], "end": occ["end"],
                              "width": width, "height": height, "fit": "contain"})
    render = [n for n in candidate["nodes"] if n["kind"] == "render"]
    if len(render) != 1 or any(n["kind"] not in {"generate", "render", "check"} for n in candidate["nodes"]):
        fail("COMPILER_UNSUPPORTED", "/nodes", "当前编译器只支持片段视频、顺序合成和人工检查")
    expected_sources = {n["id"] for n in candidate["nodes"] if n["kind"] == "generate"}
    if {i["node_id"] for i in render[0]["output_inputs"]} != expected_sources:
        fail("COMPILER_UNSUPPORTED", "/nodes/" + render[0]["id"], "合成节点必须明确引用全部片段产物")
    if any(n["kind"] == "generate" and n["depends_on"] for n in candidate["nodes"]):
        fail("COMPILER_UNSUPPORTED", "/nodes", "当前单阶段编译器不支持生成间依赖")
    if any(a["use"] == "shared_production" for a in candidate["assets"]):
        fail("COMPILER_UNSUPPORTED", "/assets", "此编译器尚未实现公共制作素材映射")
    binding = next(p for p in render[0]["parameter_inputs"] if p["name"] == "end_copy")
    copy_text = opts["parameters"][binding["variable"].removeprefix("params.")]
    if copy_text:
        if not font:
            fail("CAPABILITY_UNAVAILABLE", "/parameters/end_copy", "未配置可用字体")
        doc["assets"].append(font)
        last = x["playback"][-1]
        doc["layers"].append({"id": "end_copy", "kind": "text", "text": copy_text, "fonts": [font["id"]],
                              "start": last["start"], "end": last["end"], "x": 30, "y": height - 160,
                              "width": width - 60, "height": 120, "font_size": 32, "track": 10, "text_align": "center"})
    from app.workbench_d.commercial.schema import Project
    return Project.model_validate(doc).model_dump(mode="json"), mapped
