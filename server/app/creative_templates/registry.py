"""Server-owned contracts. Configuration readiness is separate from known capability."""

CAPABILITIES = {
    "reference_guided_video_v1": {
        "kind": "generate", "executor": "d", "output": "video", "parameters": {},
        "roles": {"first_frame": "image", "last_frame": "image", "reference_image": "image"},
        "max_inputs": 3, "max_role": {"first_frame": 1, "last_frame": 1, "reference_image": 3},
        "route": "reference_guided_video_v1",
    },
    "ordered_timeline_with_end_copy_v1": {
        "kind": "render", "executor": "d", "output": "video",
        "parameters": {"end_copy": "text"}, "roles": {"source_media": "video"}, "max_inputs": 100,
    },
    "manual_final_review_v1": {
        "kind": "check", "executor": "orchestrator", "output": None,
        "parameters": {}, "roles": {"reference_image": "image", "check_subject": "video"}, "max_inputs": 100,
    },
}
CHECKS = {"segment_coverage_v1": "structural", "product_visual_review_v1": "manual_visual"}


def readiness(candidate, routes):
    from .contracts import issue
    result = []
    for i, node in enumerate(candidate["nodes"]):
        cap = CAPABILITIES.get(node["capability_id"])
        if not cap or cap.get("route") and not routes.get(cap["route"]):
            result.append(issue("CAPABILITY_UNAVAILABLE", f"/candidate/nodes/{i}/capability_id",
                                "缺少已核实的模型路线与参考角色配置", False))
    if any(n["kind"] == "generate" and n["output_inputs"] for n in candidate["nodes"]):
        result.append(issue("STAGE_AUTHORIZATION_REQUIRED", "/candidate/nodes",
                            "多阶段生成尚未完成 T5 授权验收，仅允许预览和规划", False))
    return result
