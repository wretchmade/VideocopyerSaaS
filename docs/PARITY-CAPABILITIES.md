# D 工具能力对照

41 项原工具与 2 项品牌扩展均保留。39 项原契约完全一致；创建/编辑工程仅保留迁入版本已有的品牌字段扩展。
以下“通过”指隔离环境的本地验证。真实模型质量、两轮用户验收和目标剪映 UI 验收仍未完成。

| 工具 | 证据 | 适配与边界 |
|---|---|---|
| `d_review_brand_build` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配；测试仅验证审查声明绑定，不能替代人类视觉验收 |
| `d_bind_brand_lock` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_capabilities` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_storage_status` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配；只验证配置查询，未上传外部存储 |
| `d_authorize_budget` | `test_no_model_authority_and_expiring_quote` | 转为冻结报价；用户 HTTP/聊天回执才授权，模型不能扩大预算 |
| `d_reconcile_request` | `test_reconcile_tool_attaches_receipt_without_dispatch` | 绑定供应商确认的远端 ID；核对不产生第二次 POST |
| `d_transfer_workspace` | `test_legacy_workspace_grant_is_exact_and_source_stays_readonly` | 用户授权已配置旧工作区的精确修订；只读原库，导入项目隔离仓库 |
| `d_create_project` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_edit_project` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_list_projects` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_inspect_project` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_check_project` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_plan_build` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_submit_build` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_build_status` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_inspect_build` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_cancel_build` | `test_cancel_tool_is_global_and_cannot_cancel_other_project` | 按需求扩为当前 Web 项目全流程停止；原构建请求保留 |
| `d_retry_build` | `test_retry_returns_new_user_quote_and_preserves_ambiguous_request` | 从旧构建恢复时生成当前范围报价；确认后新尝试，未知请求不重发 |
| `d_preview_frame` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_deliver_mp4` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_prepare_studio` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_add_feedback` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_resolve_feedback` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_reopen_feedback` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_get_feedback` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_sync_feedback` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_save_view` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_canvas_status` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_record_view` | `test_browser_only_visibility_and_user_path_grants + browser.json` | 真实浏览器渲染可见后登记；模型伪造回执被拒绝 |
| `d_archive_workflow` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_list_workflows` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_rebuild_index` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_preflight_reuse` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_instantiate_workflow` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_retention_check` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配 |
| `d_choose_export` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配；文件结构/重定位已验，目标剪映 UI 待验 |
| `d_export_draft` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配；文件结构/重定位已验，目标剪映 UI 待验 |
| `d_jianying_create` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配；文件结构/重定位已验，目标剪映 UI 待验 |
| `d_jianying_import` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配；文件结构/重定位已验，目标剪映 UI 待验 |
| `d_jianying_list` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配；文件结构/重定位已验，目标剪映 UI 待验 |
| `d_jianying_inspect` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配；文件结构/重定位已验，目标剪映 UI 待验 |
| `d_jianying_edit` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配；文件结构/重定位已验，目标剪映 UI 待验 |
| `d_jianying_publish` | `test_scoped_native_tool_lifecycles` | 同一 D 核心；项目范围与文件入口适配；文件结构/重定位已验，目标剪映 UI 待验 |

测试源：[范围与控制](../tests/test_parity.py)、[实际工具生命周期](../tests/test_parity_tools.py)、[上游回归](../tests/upstream)。
汇总：[capability-matrix.json](evidence/parity/capability-matrix.json)。全部供应商请求为本地模拟；真实 FFmpeg、Codex App Server、MCP 与 Chrome 浏览器参与测试。
