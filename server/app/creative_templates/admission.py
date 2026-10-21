import re
from .contracts import issue, schema_issues, TemplateError
from .expansion import expand
from .registry import CAPABILITIES, CHECKS, readiness

TOKEN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def validate(envelope, resolve, routes=None):
    problems = schema_issues(envelope)
    if problems:
        return problems, []
    c = envelope["candidate"]

    def error(code, path, message):
        problems.append(issue(code, "/candidate" + path, message))

    groups = {}
    for key in ("sources", "assets", "input_slots", "parameters", "component_slots", "components",
                "segments", "prompt_recipes", "nodes", "requirements", "checks"):
        groups[key] = {x["id"]: x for x in c[key]}
        if len(groups[key]) != len(c[key]):
            error("DUPLICATE_ID", "/" + key, "同类 ID 必须唯一")

    def ref(group, value, path):
        if value not in groups[group]:
            error("REFERENCE_MISSING", path, "未找到 " + group + "/" + str(value))
            return None
        return groups[group][value]

    observations = {}
    for i, source in enumerate(c["sources"]):
        path = f"/sources/{i}"
        media = resource(source["media_ref"], path + "/media_ref", resolve, problems, "video")
        analysis = resource(source["analysis_ref"], path + "/analysis_ref", resolve, problems, "analysis")
        if analysis and analysis.get("source_sha256") != source["media_ref"]["sha256"]:
            error("ANALYSIS_SOURCE_MISMATCH", path + "/analysis_ref", "分析记录未绑定此源视频")
        for j, obs in enumerate(source["observations"]):
            if obs["id"] in observations:
                error("DUPLICATE_ID", path + f"/observations/{j}/id", "观察 ID 必须全局唯一")
            observations[obs["id"]] = obs
            start, end = obs["range_ms"]
            if start >= end or media and end > media.get("duration_ms", 0):
                error("SOURCE_RANGE_INVALID", path + f"/observations/{j}/range_ms", "观察时间超出真实媒体")
            if analysis and obs not in analysis.get("observations", []):
                error("ANALYSIS_SOURCE_MISMATCH", path + f"/observations/{j}", "声明必须与已登记分析记录完全一致")
    for i, asset in enumerate(c["assets"]):
        path = f"/assets/{i}"
        r = resource(asset["resource_ref"], path + "/resource_ref", resolve, problems, asset["kind"])
        if r and r.get("scope") == "instance":
            error("RESOURCE_SCOPE_INVALID", path, "公共模板包不能引用用户实例素材")
        if asset["rights"]["evidence_ref"]:
            resource(asset["rights"]["evidence_ref"], path + "/rights/evidence_ref", resolve, problems)
        if asset["use"] in {"preview", "shared_production"} and (
                asset["rights"]["status"] not in {"owned", "licensed"} or not asset["rights"]["evidence_ref"] or r and r.get("scope") != "public"):
            error("RESOURCE_SCOPE_INVALID", path + "/rights", "公开素材需要授权凭据和公共登记范围")
    preview = c["preview"]
    if preview["kind"] != "none":
        group = "sources" if preview["kind"] == "source_reference" else "assets"
        ref(group, preview["asset_id"], "/preview/asset_id")
    for i, s in enumerate(c["input_slots"]):
        if s["min_items"] > s["max_items"]:
            error("SCHEMA_INVALID", f"/input_slots/{i}", "素材数量上下限不一致")
    policy = c["output_policy"]
    if not 1 <= policy["fps"]["num"] / policy["fps"]["den"] <= 60:
        error("CAPACITY_EXCEEDED", "/output_policy/fps", "D 支持 1～60 fps")
    if not policy["min_seconds"] <= policy["default_seconds"] <= policy["max_seconds"]:
        error("DURATION_UNSATISFIABLE", "/output_policy", "默认片长超出上下限")
    for i, s in enumerate(c["segments"]):
        if s["min_count"] > s["max_count"] or s["min_seconds"] > s["max_seconds"]:
            error("DURATION_UNSATISFIABLE", f"/segments/{i}", "片段数量或时长上下限不一致")
        for rid in s["requirement_ids"]:
            ref("requirements", rid, f"/segments/{i}/requirement_ids")
    defined = {"identity." + x for x in groups["input_slots"]} | {"params." + x for x in groups["parameters"]} | {
        "segment.purpose", "segment.label", "output.duration_seconds", "output.aspect_ratio"} | {"components." + x for x in groups["component_slots"]}
    for i, recipe in enumerate(c["prompt_recipes"]):
        used = set(TOKEN.findall("\n".join(recipe["sections"].values())))
        if used - set(recipe["variables"]) or set(recipe["variables"]) - defined:
            error("VARIABLE_UNBOUND", f"/prompt_recipes/{i}/variables", "配方变量未声明或没有可解析来源")
    for i, s in enumerate(c["component_slots"]):
        if s["default_component_id"] not in s["allowed_component_ids"]:
            error("REFERENCE_MISSING", f"/component_slots/{i}/default_component_id", "默认组件不在允许列表")
        for cid in s["allowed_component_ids"]:
            component = ref("components", cid, f"/component_slots/{i}/allowed_component_ids")
            if component and component["slot"] != s["id"]:
                error("REFERENCE_MISSING", f"/component_slots/{i}", "组件槽不匹配")
    for i, component in enumerate(c["components"]):
        for key, group in (("target_segment_ids", "segments"), ("required_slot_ids", "input_slots"),
                           ("replace_requirement_ids", "requirements"), ("requirement_ids", "requirements"),
                           ("incompatible_component_ids", "components")):
            for rid in component[key]:
                ref(group, rid, f"/components/{i}/{key}")
        for j, override in enumerate(component["recipe_overrides"]):
            recipe = ref("prompt_recipes", override["recipe_id"], f"/components/{i}/recipe_overrides/{j}")
            if recipe and set(TOKEN.findall(override["text"])) - set(recipe["variables"]):
                error("VARIABLE_UNBOUND", f"/components/{i}/recipe_overrides/{j}/text", "覆盖配方引入未声明变量")
    for i, requirement in enumerate(c["requirements"]):
        check = ref("checks", requirement["check_id"], f"/requirements/{i}/check_id")
        if check and (requirement["kind"] == "structural") != (check["kind"] == "structural"):
            error("CHECK_KIND_MISMATCH", f"/requirements/{i}/check_id", "结构检查与视觉检查不能互相替代")
        for sid in requirement["target_segment_ids"]:
            segment = ref("segments", sid, f"/requirements/{i}/target_segment_ids")
            component_only = any(requirement["id"] in comp["requirement_ids"] for comp in c["components"])
            if segment and requirement["id"] not in segment["requirement_ids"] and not component_only:
                error("REQUIREMENT_UNCOVERED", f"/requirements/{i}/target_segment_ids", "声明要求必须进入目标片段的覆盖表")
        for oid in requirement["observation_ids"]:
            if oid not in observations:
                error("REFERENCE_MISSING", f"/requirements/{i}/observation_ids", "观察不存在")
    for i, check in enumerate(c["checks"]):
        if CHECKS.get(check["method_id"]) != check["kind"]:
            error("CHECK_UNREGISTERED", f"/checks/{i}/method_id", "检查方法未注册或类型不匹配")
    for i, node in enumerate(c["nodes"]):
        path = f"/nodes/{i}"
        cap = CAPABILITIES.get(node["capability_id"])
        if node["segment_id"]:
            ref("segments", node["segment_id"], path + "/segment_id")
        if node["prompt_recipe_id"]:
            ref("prompt_recipes", node["prompt_recipe_id"], path + "/prompt_recipe_id")
        if node["check_id"]:
            ref("checks", node["check_id"], path + "/check_id")
        for rid in node["requirement_ids"]:
            ref("requirements", rid, path + "/requirement_ids")
        for dep in node["depends_on"]:
            parent = ref("nodes", dep["node_id"], path + "/depends_on")
            if parent and dep["binding"] == "same_instance" and (node["scope"] != "per_segment" or parent["scope"] != "per_segment" or node["segment_id"] != parent["segment_id"]):
                error("DEPENDENCY_BINDING_INVALID", path + "/depends_on", "same_instance 只能在同一重复段中使用")
        for source in node["output_inputs"]:
            parent = ref("nodes", source["node_id"], path + "/output_inputs")
            if {"node_id": source["node_id"], "binding": source["binding"]} not in node["depends_on"]:
                error("REFERENCE_MISSING", path + "/output_inputs", "产物引用必须声明对应依赖")
            output_cap = CAPABILITIES.get(parent["capability_id"], {}) if parent else {}
            if cap and cap["roles"].get(source["role"]) != output_cap.get("output"):
                error("INPUT_TYPE_MISMATCH", path + "/output_inputs", "产物类型与输入角色不兼容")
        for slot in node["slot_inputs"]:
            s = ref("input_slots", slot["slot_id"], path + "/slot_inputs")
            if cap and s and cap["roles"].get(slot["role"]) != s["media_kind"]:
                error("INPUT_TYPE_MISMATCH", path + "/slot_inputs", "素材类型与能力角色不兼容")
            recipe = groups["prompt_recipes"].get(node["prompt_recipe_id"])
            if node["kind"] == "generate" and s and s["identity_kind"] in {"product", "person", "scene"} and recipe and "identity." + s["id"] not in recipe["variables"]:
                error("VARIABLE_UNBOUND", path + "/prompt_recipe_id", "身份参考槽必须有对应的提示词身份变量")
        bound = {}
        for param in node["parameter_inputs"]:
            if param["variable"] not in defined:
                error("VARIABLE_UNBOUND", path + "/parameter_inputs", "参数变量无来源")
            p = groups["parameters"].get(param["variable"].removeprefix("params."))
            bound[param["name"]] = p["type"] if p and param["variable"].startswith("params.") else None
        if cap and (bound != cap["parameters"] or len(bound) != len(node["parameter_inputs"]) or node["kind"] != cap["kind"] or node["executor"] != cap["executor"]):
            error("CAPABILITY_CONTRACT_MISMATCH", path, "节点类型、执行方或显式参数与能力契约不一致")
    for rid in c["adaptation_policy"]["editable_parameter_ids"]:
        ref("parameters", rid, "/adaptation_policy/editable_parameter_ids")
    pending = {n["id"]: {d["node_id"] for d in n["depends_on"]} for n in c["nodes"]}
    done = set()
    while pending:
        ready = {nid for nid, deps in pending.items() if deps <= done}
        if not ready:
            if all(d in groups["nodes"] for deps in pending.values() for d in deps):
                error("GRAPH_CYCLE", "/nodes", "执行依赖包含环")
            break
        done |= ready
        pending = {nid: deps for nid, deps in pending.items() if nid not in ready}
    if not problems:
        try:
            expand(c)
        except TemplateError as exc:
            problems.extend(exc.issues)
    blockers = readiness(c, routes or {})
    blockers.append(issue("PUBLICATION_EVIDENCE_MISSING", "/candidate/preview",
                          "发布需三个不同产品的真实系统试作、人工检查、样片和操作者审核", False))
    return problems, blockers


def resource(reference, path, resolve, problems, kind=None):
    try:
        row = resolve(reference["resource_id"])
    except (ValueError, OSError):
        problems.append(issue("ASSET_NOT_FOUND", "/candidate" + path, "受控资源不存在或不可访问"))
        return None
    if row["sha256"] != reference["sha256"] or not row.get("integrity", False):
        problems.append(issue("ASSET_HASH_MISMATCH", "/candidate" + path, "资源真实字节与引用哈希不符"))
    if kind and row["kind"] != kind:
        problems.append(issue("INPUT_TYPE_MISMATCH", "/candidate" + path, "资源媒体类型不符"))
    return row
