# 功能追踪矩阵

2026-10-16 更新：当前阶段一至四状态以 [总矩阵](total-matrix.md) 为准；第四阶段实施见 [stage4.md](stage4.md)。A07—A11 细节见 [stage3.md](stage3.md)；61 行 provider/model 清单保留不减，见 [provider-model-matrix.json](evidence/provider-model-matrix.json)。下方原调用点追踪中“后续/阶段四”等文字是历史计划，不应当作当前状态。

来源代号：U＝本次用户功能要求；B＝精确版本黑盒命令和公开输入合同；D＝交接 D 源码及合同。所有旧调用点详见 `evidence/call-sites.json`，包含文件哈希和行号。下面是独立规格，不沿用上游生产技能正文。

## A01—A06

| ID | 基线/原 D 调用位置与现状 | 决定及独立功能规格 | 新实现位置 | 来源 | 验收 | 未验证/边界 |
|---|---|---|---|---|---|---|
| A01.1 | baseline `src/native.mjs`、`scripts/native-control.mjs` 使用 SVML/Run | 重写：工程描述显式素材、层、任务、音频、样式、输出；拒绝未知字段 | `commercial/schema.py` | U,D | 静态错误、缺资产、帧区间、循环依赖 | 不解析任意 SVML |
| A01.2 | `service.mjs` 修订与回执、D 原合同修订 | 重写：版本 0→1 显式迁移，修订不可变、baseRevision 乐观锁 | `schema.py`、`engine.py`、`store.py` | U,D,B | 版本升级、陈旧修订拒绝、回读旧修订 | 跨任意旧版本自动升级未承诺 |
| A01.3 | `baseline_bridge.py` 归档合同而未转换 | 替换：只读 SQLite 工作区、核验修订/素材许可并实际转换可表达图层 | `bridge.py` | U,D | 导入、渲染及原数据库哈希不变 | 复杂字幕/运动/语义事件会明确拒绝，须显式创作 D Project |
| A02.1 | Hypit check/plan | 重写：静态校验、字体检查、素材哈希、任务 DAG、准确运行时哈希 | `engine.py` | U,B | check/plan 经真实入口执行 | 模型任务可描述，执行明确报阶段三边界 |
| A02.2 | Hypit build/status/inspect | 重写：SQLite 回执、并发提交去重、依赖顺序、节点检查点、持久事件 | `store.py`、`worker.py` | U,B | 并发回执、重复 build、真实进程重启、输出查询 | 依赖任务顺序调度；不承诺集群调度 |
| A02.3 | Hypit cancel、D 原后台执行 | 替换：持久取消、进程树清理、错误存储、显式 retry，租约隔离不同尝试 | `worker.py`、`processes.py` | U,D | 排队取消、运行中取消、强杀后恢复、租约隔离、失败恢复 | 外部页面提交不保证 exactly-once；本阶段测试只用本地页面交互 |
| A03.1 | 原 D `composition_renderer.py`、`presentation.py`、`frame_clock.py` | 独立实现：有理帧率、半开帧区间、稳定轨道顺序、裁切、contain/cover/stretch | `render.py` | U,D | 多轨像素采样、裁切、动态同素材布局对照 | 大量视频层的性能未压测 |
| A03.2 | Hypit composition/temporal、原 D motion | 独立实现：位置、缩放、旋转、透明度的线性/保持/平滑关键帧；普通图层淡入淡出；显式预乘 alpha crossfade/wipe/push（R1 修复） | `render.py`、`schema.py` | U | alpha 精确像素、动画端点、交叉淡化 | 专用 page-turn/复杂变形等完整效果库属于后续组件迁移 |
| A03.3 | 原音轨合成 | 重写：48kHz 样本域裁切、延时、混音、音量与淡化；最终时间戳由样本数建立 | `render.py` | U,D | 30000/1001 帧率、音频时长；基线同音轨关联度 | 多语言自动对齐/ASR 不在阶段二 |
| A04.1 | Hypit renderer、原 D FFmpeg | 替换：同一 rasterizer 预览与完整 PNG 帧序列，精确帧边界 | `render.py`、`engine.preview` | U | preview PNG、逐帧哈希、alpha MOV | 无 GPU/高分辨率吞吐承诺 |
| A04.2 | 原 native 编码/交付 | 替换：外部 LGPL FFmpeg 适配；OpenH264/AAC MP4、PNG/RGBA MOV；核验帧数/尺寸/音轨/时长后交付 | `render.py`、`engine.deliver` | U,B | 实际编码、浏览器播放、交付下载、损坏产物拒绝 | alpha MOV 浏览器原生播放不保证；发行构建/专利仍须另审 |
| A05.1 | `caption_browser.py`、`caption_capture_runner.mjs` 调 Hypit | 替换：显式字体与 cmap 回退、中文逐字排版、换行/标点避头、水平/垂直对齐 | `Rasterizer.caption` | U,D | 中文/Latin 回退、缺字/溢出拒绝；同字体中文标题对照 | 复杂文字塑形、彩色 Emoji 全矩阵未验收 |
| A05.2 | caption/typography 扩展 | 独立实现：词级帧时间窗高亮、描边、阴影、层关键帧动画、透明图层 | `schema.Word`、`render.py` | U | 不同帧文字差异、透明像素、时间窗约束 | 原 Fine Caption 全部 recipe 不宣称等价 |
| A06.1 | `browser_capture.mjs`、media_processors 调 Hypit capture | 替换：独立 Playwright context、截图/定步录制、尺寸/有理 fps、字体/图像/selector 等待 | `capture.py`、`browser.mjs` | U | 三帧点击变色、截图与视频进入实际任务 DAG | WebRTC、实时外部媒体、反自动化网站未验收 |
| A06.2 | 浏览器登录态 | 新实现：每次任务新 context、禁用 service worker、显式允许来源、上下文销毁 | `browser.mjs` | U | 第一任务设置 cookie 后第二任务无 cookie；超时持久失败 | 不自动带入用户登录态；用户登录导入流程未提供 |

## 基线全部 43 个命令的接口边界

各行均记录现状、替代决定、独立行为、来源、验收和未完成项。来源 B 为原命令表的只读审计副本；该副本不进入插件。旧调用位置统一为 `baseline.py → baseline-gateway.mjs → baseline src/service.mjs`，native 命令再进入 `src/native.mjs`；特定组件/扩展的间接调用见机器清单。

| 原入口 | 决定 / 当前独立行为 | 来源 | 验收 / 未完成 |
|---|---|---|---|
| d_storage_status | 后续替换：存储适配器输出连接状态，不返回凭证 | B,U | 阶段三；不转发旧 COS |
| d_seed_vc_status | 后续替换：独立模型/权重/许可证状态 | B,U | 阶段三，未验收 |
| d_seed_vc_convert | 后续替换：受授权的音色转换任务 | B,U | 阶段三；未调用模型 |
| d_prepare_canvas | 替换为 D 前端项目编辑器 | B,U,D | 创建→编辑→渲染真实 UI；完整分组画布后续 |
| d_canvas_status | 后续完善当前视图展示回执 | B,U | 服务状态存在；跨宿主可见回执未实现 |
| d_jianying_create | 后续独立草稿接口 | B,U | 阶段四 |
| d_jianying_import | 后续独立导入和格式校验 | B,U | 阶段四 |
| d_jianying_list | 后续草稿项目查询 | B,U | 阶段四 |
| d_jianying_inspect | 后续只读轨道/媒体检查 | B,U | 阶段四 |
| d_jianying_edit | 后续不可变编辑修订 | B,U | 阶段四 |
| d_jianying_publish | 后续用户目标目录安装 | B,U | 阶段四；本次不写剪映目录 |
| d_import_project | 替换为 D Project 创建和只读旧 D 导入 | B,U,D | 旧工作区桥接通过；任意上游项目不接受 |
| d_prepare_studio | 后续审片副本 | B,U | 阶段四 |
| d_sync_feedback | 后续反馈修订同步 | B,U | 阶段四 |
| d_create_project | 已替换：名称、版本化工程、素材快照 | B,U | MCP/HTTP/干净包 |
| d_get_project | 替换为 d_inspect_project，精确修订查询 | B,U | 回读旧修订 |
| d_list_projects | 已替换：本地核心项目列表 | B,U | MCP/HTTP/UI |
| d_get_events | 由 d_inspect_build 返回持久事件 | B,U | 租约和节点事件，通用项目事件后续 |
| d_propose_change | 改为本地工程草稿 + 明确编辑提交 | B,U | UI 保留未保存文本；服务端提案对象后续 |
| d_commit_change | 替换为 d_edit_project，不可变修订与冲突保护 | B,U | 修订并发用例 |
| d_discard_change | UI 放弃未保存草稿，项目不变 | B,U | 不是同名服务端空实现；完整提案协议后续 |
| d_undo_change | 可回读旧修订并提交为新修订 | B,U | 不直接改写历史；专用撤销 UI 后续 |
| d_plan_build | 已替换：任务依赖、静态检查、运行时哈希、零模型请求 | B,U | 实际计划与冻结构建 |
| d_authorize_budget | 后续预算授权 | B,U | 阶段三；无收费工具暴露 |
| d_configure_runtime | 替换为显式环境配置和运行时身份 | B,U | 精确二进制及 DLL 哈希；不继承旧凭证 |
| d_submit_build | 已替换：冻结修订提交、重复请求去重 | B,U | 构建 ID 复用、错误状态持久化 |
| d_inspect_build | 已替换：状态、节点、事件、产物和错误 | B,U | 重启后查询 |
| d_reconcile | 由状态查询及服务恢复循环接管 | B,U | 杀进程后租约恢复 |
| d_cancel_build | 已替换：持久取消并清理子进程 | B,U | 排队及运行中取消 |
| d_deliver_mp4 | 已替换：成功结果校验、交付副本及修订绑定 | B,U | 干净包实际下载；损坏文件拒绝 |
| d_choose_export | 后续导出选择记录 | B,U | 阶段四 |
| d_export_draft | 后续剪映轨道映射与降级报告 | B,U | 阶段四 |
| d_install_draft | 后续目标路径检查和安装 | B,U | 阶段四 |
| d_record_acceptance | 后续审片/剪映实机验收记录 | B,U | 阶段四 |
| d_save_view | 后续完整画布视口持久化 | B,U | 当前仅保留项目最近构建 ID |
| d_add_feedback | 后续绑定修订/帧的反馈 | B,U | 阶段四 |
| d_resolve_feedback | 后续反馈状态流转 | B,U | 阶段四 |
| d_list_workflows | 后续独立流程库索引 | B,U | 阶段三 |
| d_rebuild_index | 后续可重建索引 | B,U | 阶段三 |
| d_preflight_reuse | 后续素材与接口兼容预检 | B,U | 阶段三 |
| d_instantiate_workflow | 后续独立实例及新授权 | B,U | 阶段三 |
| d_retention_check | 后续媒体/项目保留策略 | B,U | 阶段三 |
| d_diagnostics | 核心 check、plan、inspect、health 覆盖当前范围 | B,U | 全部原扩展诊断后续 |

## 资产与扩展边界

排行榜、Last War、Seedance、Seedream 的 author-kit/composition/temporal 引用均隔离在上游审计树，不进入核心。`component_library` 中有 `hypit_reference` 的条目不得因位于 D 目录就判定独立；完整组件来源审查及替代实现属于阶段三。模型权重、声音/人脸模型、字体、示例素材、技能、提示词、编译产物和 TGZ 的文件哈希/分类见 `baseline-files.csv`；没有“改名后可商业分发”的推断。
