# 第四阶段开发与待验收交付

2026-10-16。阶段二 R1/R2、S3-R1 与 **S4-R1** 已由独立审查在其明确范围内接受并关闭；阶段三、四整体仍为 **PARTIAL**。S3-G1/G2、S4-G1/G2/G3 全部保留。总范围见 [阶段一至四总矩阵](total-matrix.md)。

## S4-R1 整改：保留切点前后的运动

**独立复验已通过，限定范围关闭。** 根任务独立复制并执行原复现脚本、重跑 33 项针对性测试：0 失败/错误/跳过，12 组共 172 帧 RGBA 精确一致，旧修订哈希未变；native 关键帧最大误差约 `2.1599274253603085e-05`，仅为整数微秒量化，不代表剪映实机验收。根任务另行校验 dev.2 ZIP SHA `93697ef2270b788f614c4d93d3ff9983b3b530e0611121490e7d86ff4e83f645`，安全解包后独立运行 41 工具的真实 MCP 核心、审片、工作流及草稿闭环通过。签收原文见 [独立复验记录](evidence/s4-r1-independent-review.json)，原证据位于只读审查树 `artifacts/d-stage4-r1-review/`。

此关闭仅确认已支持编辑的保留帧正确性，以及不可保真操作的明确拒绝。复杂/烘焙源配方时间编辑和带淡化音频裁切仍属于 **S4-G2 能力缺口**，不得据此表述为完整支持。S3-G1/G2、S4-G1/G2/G3 继续开放；本次仅同步签收，不发起新阶段、发布或市场安装，已验收的开发 ZIP 保持不变。

原审查确认：F0 x=0 → F29 x=100 的图片在 F15 分割，左侧 F14 从 48.275862 变成 0。原因是只保留首帧和区间内部关键帧，遗漏最后保留帧。本次原审查脚本在本工作树副本执行，F14 切前/切后均为 **48.275862068965516**，原修订哈希不变；原审查目录只读。

- `Drafts.trim` 对 position x/y、scale、rotation、opacity 固定每个保留帧的值，包含 `end-1`；重复裁切和单帧裁切也适用。只补端点仍可能因浮点重新插值造成 1 级 alpha 差，因此没有停在端点补丁。`render.animated` 用二分查找，在关键帧处直接返回精确存储值，避免再次计算引入舍入差。
- 普通视觉 fade_in/fade_out 转为**原时间轴的逐帧透明度包络**，清除片段局部 fade；保留重叠淡化的乘积，不在切点重新淡入/淡出。原生导出也使用相同帧采样，最后零值位于 `end-1`，不再误写成片段末尾减 1 微秒。
- 非线性 hold/smooth、组件、需伴随渲染的文字/色块/复合透明度等源配方，管理接口的 trim/split/move 返回 `TEMPORAL_EDIT_UNSUPPORTED`；显式转场组继续拒绝。它们可能依赖 local age、区间长度或程序绝对帧，不能通过重新生成冒充原媒体裁切。可显式将已渲染媒体作为普通视频素材导入后编辑；不会自动替换为不透明黑盒。
- 带音频 fade_in/fade_out 的 trim/split 同样明确拒绝，因为当前音频 schema 不能表达切开后的原包络。无淡化音频保持 source_start、音量和样本内容。被拒操作不新增修订，也不改写旧文件。
- 密集帧采样会增加草稿关键帧数量；这是帧域保真方案，不承诺长片关键帧导出性能或剪映的亚帧插值视觉验收。

复现：`./scripts/verify_d_s4_r1.ps1`。新增 20 项针对性用例，加现有相关用例共 **33 项**；没有以之前 48 项通过代替本缺陷验证。12 组图像/真实视频 × split/trim/单帧 × 动画透明度/重叠淡化，共比较 172 个保留帧的**完整 RGBA 字节**；逐帧检查导出 native keyframes、target/source 微秒计时；无淡化音频 split 的实际 PCM 字节完全相同，trim 的保留样本完全相同；另测重复裁切、非线性/组件/烘焙和音频淡化拒绝。

证据：[s4-r1-tests.xml](evidence/s4-r1-tests.xml)、[原复现结果](evidence/s4-r1-original-repro.json)、[整改汇总及逐帧案例](evidence/s4-r1-remediation.json)。native 值比较允许整数微秒时间量化带来的 `<0.0001` 原生单位误差；RGBA 与 PCM 比较不使用该容差。此证据仍不代替 S4-G1 的剪映实机打开/编辑/保存/重开验收。

## 本轮实现

| 能力 | 实际行为 | 验证及限制 |
|---|---|---|
| S3-R1 报价过期恢复 | 先读取持久请求和冻结 payload；新 admission/dispatch 仍需新鲜报价与预算；已确认 remoteId 的 accepted/running/succeeded/cancel_requested 请求可继续 GET/下载；未知提交不自动重发 | 四种过期恢复分支、新提交零 POST/零预留、全新 Python 宿主/执行器进程恢复；报价时钟单独推进 7200 秒，不改变租约时钟。独立复核已接受此缺陷修复 |
| A12 审片 | 成功构建生成自有媒体副本；project/revision/build/documentHash/fps/frames 固定；逐帧反馈、resolve/reopen 乐观锁、事件历史、离线副本 ZIP 和 JSON 同步去重 | 测试修改工程后旧审片哈希不变；越界帧/旧版本/同步冲突拒绝。离线 HTML 不调用外部服务；反馈由用户导出后回传 |
| 工作流 | 复制素材到独立归档；保存源修订、参数声明、资产来源/许可/哈希、组件/操作/实现依赖哈希；已登记归档重建搜索索引；预检缺失/变更资产；显式替换与 provider/model 重绑定 | 新项目新 ID/revision 0，无预算继承、max_cost=0；配置和密钥不导入；已知凭证字段拒绝归档。实现依赖变化要求显式重归档/迁移，不默默继续。索引可重建不等于任意外部工作流自动导入 |
| 制作画布 | 任务分组、子卡、拖动/分组移动、折叠、缩放/键盘平移、布局和视口 CAS 保存；任务节点记录实际 tool/provider/wire model/模型权重哈希；时间线；窄屏下工具面板落入下方抽屉 | 可见 DOM 绘制后才发送精确 revision/hash/viewVersion/session 回执。服务启动和 MCP 查询不产生可见回执；回执不是“真人已阅读”的证明 |
| B05 多轨草稿 | 使用独立可选 pyJianYingDraft 0.3.1 序列化 image/video/text/audio 独立轨道；位置、尺寸、裁切、音量、线性关键帧；源媒体归档；D 文本仍可编辑 | 真实 PNG/MOV/WAV/字体输入；检查 native 轨道、源时间、裁切、关键帧、音量。原生字体/坐标/裁切视觉兼容仍需剪映实机确认 |
| 草稿编辑 | create/import/list/inspect/edit/publish；split/trim/move/volume/subtitle/crop/delete；不可变修订、baseRevision 冲突、文件 SHA 手工修改检查 | D 自有 sidecar 可导入完整已支持工程；外部明文仅严格支持简单无变换媒体/音频子集；复杂文字、变速、特效/动画等明确 MIGRATION_REQUIRED。加密/锁定/运行中的编辑器拒绝，不提供解密 |
| 导出与安装 | delivery receipt → choose_export → export_draft 分开；精确成片/构建/修订/哈希绑定；publish 只接受新显式目录；复制素材并迁移原生 JSON、内嵌文本字体 JSON 和 D sidecar 路径，再重算哈希 | 测试新目录安装、重导入、旧目录拒绝、文件篡改拒绝；复制在临时兄弟目录完成后改名。异常可留下 staging 目录或已装但回执未提交的目录，重试拒绝覆盖，需明确检查处理 |

## 烘焙与兼容边界

复杂组件、色块、词级动态文字、非线性/复合透明度动画和显式转场组，必须显式 `allowBaked=true`，才生成**该图层或相邻转场组**的透明 MOV 伴随素材。其他图层、文本与音轨仍独立。`baked` 和 `limitations` 清单随每个修订保存，原 D 工程也随包归档。没有把整段成片导回单一视频轨道称为可编辑；如果输入本来只有一个复杂组，该组内部仍明确不可编辑。

分数帧率以微秒保留源时间，但 native fps 使用整数，必须显式接受差异。字幕原生字体度量、复杂塑形、位置/裁切/关键帧及透明 PNG-MOV 在剪映中的实际表现没有软件实测保证。原生转场目前使用明确的局部烘焙，并未宣称所有转场都可原生编辑。

本次通过 computer-use 的 `sky.list_apps` 没有发现 Jianying/CapCut；已知 `%LOCALAPPDATA%/JianyingPro/Apps` 为空，未发现可启动编辑器。因此 **S4-G1：打开→编辑→保存→重开仍未验收**。结构/文件/哈希测试不代替 UI 证据。本轮只写 `artifacts/d-commercial/` 下隔离测试草稿，没有触碰用户个人剪映目录。

## 复现与证据

在仓库根目录，先使用已有独立核心环境；可选剪映序列化环境单独安装，不能混入核心锁文件：

```powershell
.commercial-env/Scripts/python.exe -m venv .jianying-env
.jianying-env/Scripts/python.exe -m pip install -r plugins/workbench-d/requirements-jianying.lock.txt
$env:D_JIANYING_PYTHON="$PWD/.jianying-env/Scripts/python.exe"
./scripts/test_d_core.ps1 -Python "$PWD/.commercial-env/Scripts/python.exe"
# apps/web 内：TypeScript --noEmit 与 D 专用 Vite build
.commercial-env/Scripts/python.exe scripts/build_d_core.py
# 配置 D_FFMPEG、D_FFPROBE、D_JIANYING_PYTHON 后：
.commercial-env/Scripts/python.exe scripts/verify_d_core_clean.py
./scripts/verify_d_stage3_ui.ps1 # 当前脚本同时验证第三、第四阶段控件
.commercial-env/Scripts/python.exe scripts/audit_d_stage4.py
```

- [core-tests.xml](evidence/core-tests.xml)：整改前 48 项完整回归历史记录，随后独立审查同样重跑通过但发现 S4-R1；不能据此否认新缺陷。[s4-r1-tests.xml](evidence/s4-r1-tests.xml) 是当前整改的针对性结果；[stage4-tests.xml](evidence/stage4-tests.xml) 为首版 7 项第四阶段后端验证历史记录。
- [ui.json](evidence/ui.json)：真实浏览器创建/渲染/播放、可见回执、布局保存、F4 反馈与解决/重开、归档预检、绑定成片导出、分割和新目录安装；桌面与 440px 截图在 `artifacts/d-commercial/ui/stage4-*.png`。
- [clean-package.json](evidence/clean-package.json)：真实 staged MCP 新进程、旧核心闭环和第四阶段工具；[clean-unpacked.json](evidence/clean-unpacked.json)：从开发 ZIP 解包后再运行相同闭环。41 个工具均列出；没有 SQLAlchemy/可解析 Hypit；服务启动不伪造可见回执。
- [stage4-report.json](evidence/stage4-report.json)：原独立审查及 S3-R1 失败证据前后 SHA；原复现脚本只复制到本工作树执行，现为 **POST 1 / GET 1 / succeeded**，见 [stage4-quote-recovery.json](evidence/stage4-quote-recovery.json)。[source-unchanged.json](evidence/source-unchanged.json)：权威源树 329 文件未改。
- [jianying-dependencies.json](evidence/jianying-dependencies.json)：可选环境 7 个 distribution 的实际文件哈希、版本与许可文件；`requirements-jianying.lock.txt` 和 `JIANYING-NOTICE.md` 随源码开发包保存。pyJianYingDraft Apache-2.0 公开 API 复用不构成剪映商业兼容认证。
- [distribution-stage4.json](evidence/distribution-stage4.json)：开发源码 ZIP 连续两次打包 SHA 一致，清单逐文件核验；不含外部二进制/权重，未发布或安装市场。脚本 `package_d_development.py` 可重现。

## 保留的未完成项

**S3-G1**：61 provider/model 行仍是完整追踪清单；真实服务、当前协议/取消/实时计价、模型质量与 COS 实账号验证未完成。未下载真实语音/分割模型权重，没有付费模型调用或外传生产素材。

**S3-G2**：完整组件参数与动画编排、GLB/FBX 3D 加载、复杂 LastWar 视觉对齐未完成；2D 叠加不等于 3D 完成。

**S4-G2**：跨场景原生草稿视觉对照、外部复杂明文/加密草稿迁移、全部原生转场和复杂文本样式未验收。当前保留明确降级或拒绝路径。

**S4-G3**：自有实现与核心分发闭包可复现；最终商业二进制包、模型/素材权属、编码器专利和再分发条款仍需针对实际发布形式审查。未发布、未安装市场、未覆盖旧草稿，也没有整体法律/商业清白声明。
