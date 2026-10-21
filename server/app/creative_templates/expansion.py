"""Pure, bounded integer-frame allocation and graph expansion; no model or D I/O."""
import copy
import math
from fractions import Fraction
from .contracts import fail, digest


def frames(seconds, fps, rounding="nearest"):
    f = Fraction(str(seconds)) * fps["num"] / fps["den"]
    if rounding == "ceil":
        return math.ceil(f)
    if rounding == "floor":
        return math.floor(f)
    return math.floor(f + Fraction(1, 2))


def options(candidate, supplied=None):
    supplied = {} if supplied is None else supplied
    if not isinstance(supplied, dict) or any(k in supplied and not isinstance(supplied[k], dict) for k in ("output", "parameters", "component_selections", "bindings")):
        fail("SCHEMA_INVALID", "/options", "选项及其分组必须是对象")
    if set(supplied) - {"output", "parameters", "component_selections", "bindings"}:
        fail("SCHEMA_INVALID", "/options", "未知预览选项")
    policy = candidate["output_policy"]
    output = {"duration_seconds": policy["default_seconds"], "aspect_ratio": policy["aspect_ratios"][0], **supplied.get("output", {})}
    if set(output) - {"duration_seconds", "aspect_ratio"} or type(output["duration_seconds"]) not in (int, float):
        fail("SCHEMA_INVALID", "/output", "输出选项类型错误")
    if not policy["min_seconds"] <= output["duration_seconds"] <= policy["max_seconds"] or output["aspect_ratio"] not in policy["aspect_ratios"]:
        fail("DURATION_UNSATISFIABLE", "/output", "片长或画幅超出模板范围")
    params = {p["id"]: p["default"] for p in candidate["parameters"]}
    if set(supplied.get("parameters", {})) - params.keys():
        fail("REFERENCE_MISSING", "/parameters", "未声明的参数")
    params.update(supplied.get("parameters", {}))
    for p in candidate["parameters"]:
        v = params[p["id"]]
        if not isinstance(v, str) or (p["type"] == "text" and len(v) > p["max_length"]) or (p["type"] == "enum" and v not in p["values"]):
            fail("SCHEMA_INVALID", "/parameters/" + p["id"], "参数不符合声明")
    selections = {s["id"]: s["default_component_id"] for s in candidate["component_slots"]}
    if set(supplied.get("component_selections", {})) - selections.keys():
        fail("REFERENCE_MISSING", "/component_selections", "未声明的组件槽")
    selections.update(supplied.get("component_selections", {}))
    components = {x["id"]: x for x in candidate["components"]}
    for s in candidate["component_slots"]:
        selected = selections[s["id"]]
        if not isinstance(selected, str) or selected not in s["allowed_component_ids"] or selected not in components:
            fail("REFERENCE_MISSING", "/component_selections/" + s["id"], "组件不在允许范围内")
        if set(components[selected]["incompatible_component_ids"]) & set(selections.values()):
            fail("COMPONENT_CONFLICT", "/component_selections", "组件互不兼容")
    bindings = supplied.get("bindings", {})
    if not isinstance(bindings, dict) or set(bindings) - {s["id"] for s in candidate["input_slots"]}:
        fail("REFERENCE_MISSING", "/bindings", "未声明的素材槽")
    for key, value in bindings.items():
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value) or len(value) != len(set(value)):
            fail("SCHEMA_INVALID", "/bindings/" + key, "素材引用必须是无重复的 ID 数组")
    return dict(output=output, parameters=params, component_selections=selections, bindings=bindings)


def expand(candidate, supplied=None, previous=None):
    opts = options(candidate, supplied)
    fps = candidate["output_policy"]["fps"]
    target = frames(opts["output"]["duration_seconds"], fps)
    segments = candidate["segments"]
    low = [frames(s["min_seconds"], fps, "ceil") for s in segments]
    high = [frames(s["max_seconds"], fps, "floor") for s in segments]
    if any(a > b for a, b in zip(low, high)):
        fail("DURATION_UNSATISFIABLE", "/segments", "没有符合整数帧边界的时长")
    # Enumerate reachable min/max sums, pruning identical states; finite server ceiling.
    order = sorted(range(len(segments)), key=lambda i: (-segments[i]["expansion_priority"], i))
    states = {(0, 0): ()}
    for i, s in enumerate(segments):
        next_states = {}
        for (lo, hi), counts in states.items():
            for count in range(s["min_count"], s["max_count"] + 1):
                key = (lo + count * low[i], hi + count * high[i])
                if key[0] <= target:
                    proposal = (*counts, count)
                    prefix = [j for j in order if j <= i]
                    priority = lambda cs: (sum(cs), tuple(-cs[j] for j in prefix))
                    if key not in next_states or priority(proposal) < priority(next_states[key]):
                        next_states[key] = proposal
        states = next_states
        if len(states) > 50000:
            fail("CAPACITY_EXCEEDED", "/segments", "片段组合超过服务器搜索上限")
    feasible = [counts for (lo, hi), counts in states.items() if lo <= target <= hi]
    if not feasible:
        fail("DURATION_UNSATISFIABLE", "/output/duration_seconds", "无法同时满足全部必需段和时长上下限")
    counts = min(feasible, key=lambda cs: (sum(cs), tuple(-cs[i] for i in order)))
    old = {}
    for item in previous or []:
        old.setdefault(item["segment_id"], []).append(item["occurrence_id"])
    playback = []
    for i, (s, count) in enumerate(zip(segments, counts)):
        for index in range(count):
            prior = old.get(s["id"], [])
            occurrence = prior[index] if index < len(prior) else s["id"] + "_" + str(index + 1)
            playback.append({"segment_id": s["id"], "occurrence_id": occurrence, "label": s["label"],
                             "purpose": s["purpose"], "frames": low[i], "max_frames": high[i], "weight": s["weight"],
                             "requirement_ids": list(s["requirement_ids"])})
    if len(playback) > 100:
        fail("CAPACITY_EXCEEDED", "/segments", "展开片段超过 100")
    remaining = target - sum(x["frames"] for x in playback)
    # Weighted fair allocation by additional frames; stable declaration-order tie-break.
    extra = [0] * len(playback)
    while remaining:
        eligible = [i for i, x in enumerate(playback) if x["frames"] < x["max_frames"]]
        i = min(eligible, key=lambda j: (Fraction(extra[j], playback[j]["weight"]), j))
        playback[i]["frames"] += 1
        extra[i] += 1
        remaining -= 1
    components = {x["id"]: x for x in candidate["components"]}
    for cid in opts["component_selections"].values():
        component = components[cid]
        for item in playback:
            if item["segment_id"] in component["target_segment_ids"]:
                item["requirement_ids"] = sorted((set(item["requirement_ids"]) - set(component["replace_requirement_ids"])) | set(component["requirement_ids"]))
    at = 0
    for item in playback:
        item.update(start=at, end=at + item["frames"])
        at = item["end"]
    graph, by_node = [], {}
    for node in candidate["nodes"]:
        occurrences = [x for x in playback if x["segment_id"] == node["segment_id"]] if node["scope"] == "per_segment" else [None]
        by_node[node["id"]] = []
        for occurrence in occurrences:
            oid = occurrence["occurrence_id"] if occurrence else None
            nid = "t_" + digest([node["id"], oid])[:24]
            row = {"id": nid, "template_node_id": node["id"], "occurrence_id": oid,
                   "kind": node["kind"], "segment_id": node["segment_id"], "depends_on": []}
            by_node[node["id"]].append(row)
            graph.append(row)
    if len(graph) > 100:
        fail("CAPACITY_EXCEEDED", "/nodes", "展开节点超过 D 的 100 节点上限")
    for row in graph:
        node = next(n for n in candidate["nodes"] if n["id"] == row["template_node_id"])
        for dep in node["depends_on"]:
            targets = by_node.get(dep["node_id"], [])
            row["depends_on"].extend(x["id"] for x in targets if dep["binding"] == "all_instances" or x["occurrence_id"] == row["occurrence_id"])
    coverage = [{"occurrence_id": x["occurrence_id"], "requirement_id": r,
                 "status": "structural_pending" if next(q for q in candidate["requirements"] if q["id"] == r)["kind"] == "structural" else "visual_pending"}
                for x in playback for r in x["requirement_ids"]]
    return {"options": opts, "fps": fps, "frames": target, "actual_seconds": target * fps["den"] / fps["num"],
            "rounding": "nearest_frame_half_up", "playback": playback, "graph": graph, "coverage": coverage,
            "view_kind": "template_preview", "model_calls": 0}
