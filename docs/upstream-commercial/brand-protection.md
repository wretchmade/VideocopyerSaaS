# 商标／物件锚定：调研、实现与验收

日期：2026-10-19。D5-03 / D5-11 / D5-17；2.0.0-beta.1 的本地源码增量，未发布、未安装到个人插件市场。源路径为用户指定 commercial-d；源文件哈希与验证产物见 `evidence/brand-protection-verification.json`。

## Higgsfield 证据边界

本次查看官方公开资料，并用 REA 静态解析公开页面实际引用的入口 JS 和 Marketing Studio 模块；没有登录、付费生成或访问后台实现，没有复制其代码。

- [官方 Marketing Studio 帮助](https://higgsfield.ai/creator-hub/help-center/tools/how-do-i-use-marketing-studio-to-create-video-ads) 支持品牌档案复用，不能证明逐帧像素保证。
- [官方汽车广告教程](https://higgsfield.ai/blog/ai-car-commercial-youtube-guide) 分开引用完整产品图和裁切 Logo，描述徽标几何，部分镜头采用静止机位。
- [Seedance 2.5 R2V 接口](https://open.higgsfield.ai/models/bytedance/seedance-2.5/reference-to-video/api-reference) 提供参考图片/视频/音频；所查接口未公开 brand_lock/拓扑约束/单应变换字段。不公开不等于内部不存在。
- [Ads Studio 说明](https://higgsfield.ai/blog/higgsfield-ads-studio) 主要针对静态广告，不能直接证明视频底层实现。

Gemini 报告中的“模型控制层每帧硬约束”“任意旋转下拓扑强制不变”和“确定性局部合成属于 Higgsfield 的实现”均未得到本次证据支持。以下设计是 D 的独立工程选择。

REA Evidence：`ev_10a9f9c773463b6c23e5d533259fb231b525f388d7a64ecdb6ff0087d8617a00`、`ev_152897115906044acc46292f6ae78d6de125ae585223e1eb9391946665780ed1`。覆盖 partial：入口触发资源上限，页面模块未截断，但外部依赖、实际网络运行和服务器机制未知。完整导出：`D:/P-project/Rehypit/higgsfield-research/rea-evidence-bundle.json`；来源及原始文件哈希：同目录 `provenance.json`。

## 实现

1. **生成前**：`Task.brand_reference` 要求已导入首帧与身份图片，以及准确输入角色；追加低运动/结构保持的生成指导，不发送虚构的模型硬锁参数，不改变预算与远程请求去重。
2. **合成时**：`Layer.brand_lock` 的 screen 保留原图比例与固定位置；planar 使用逐帧四角、可见性和遮罩，每帧重新采样原始资产。绑定源图、底片、底片变换、画布、时间轴与遮罩的 hash；变化时旧定位拒绝复用。
3. **交付前**：`d_review_brand_build` 绑定实际输出哈希记录审查；没有通过记录时拒绝品牌成片交付。记录是调用者视觉审查，不是自动质量评分，也不能由“渲染成功”推导通过。
4. **操作入口**：新增 `d_bind_brand_lock`、`d_review_brand_build`；工作台提供固定/平面定位入口及检查记录。插件技能要求先选合适方案，缺少定位时不编造轨迹。剪映保护层需要显式接受局部烘焙，保留透明独立图层。

详细字段与流程：`plugins/workbench-d/skills/workbench-d/references/brand-protection.md`。既有普通项目无需品牌审查；只有声明品牌策略的构建启用门禁。历史交付回执保持不可变。

## 验证与限制

新增 27 项品牌测试，涵盖每帧原图裁片一致性、透视四角映射、隐藏/透明遮挡、缺帧/错误几何、资产/时间轴失效、真实 MOV 编码和交付门禁；连同已有测试共 95 项通过。既有 S3-R1 请求恢复及 S4-R1 时序回归保留。测试没有付费调用。

实际前端构建通过；独立浏览器从表单导入 48 帧定位、保存新修订、渲染、播放 MP4、验证未审查拒交、通过后交付、改为不通过后再次拒交，页面运行错误为零。复现脚本 `scripts/verify_brand_ui.mjs` 需要 D_REVIEW_SOURCE、D_TEST_PYTHON、D_FFMPEG、D_FFPROBE、D_PLAYWRIGHT_MODULE、PLAYWRIGHT_BROWSERS_PATH、D_BRAND_FIXTURE（上段演示目录）和 D_BRAND_UI_OUTPUT（独立测试目录）。这是合成夹具的 UI 控制验收，脚本中的 approved=true 不代表真人审看或真实模型质量通过。

新本地包在 `artifacts/brand-protection-distribution/`，原 `artifacts/distribution/` 基线包未覆盖。实际解包 manifest 启动器、43 工具、工具参考一致性、HTTP 静态资源与 MCP 共享项目、60 帧旧演示渲染/交付均通过。插件 ZIP 重复构建哈希相同；最终校验和见该目录 SHA256SUMS.txt。未将此增量安装到当前用户的插件缓存；使用该源目录或增量包时才具备新能力。

`scripts/verify_brand_protection.py --output <new-directory>` 生成 48 帧移动平面及遮挡演示，并输出 MP4、逐帧 PNG、定位文件、原件、拼图与 hash。当前演示位于 `D:/P-project/Rehypit/brand-anchor-work/demo/`；它是人工构造几何的合成测试，绝不代表真实 Seedance 对照。原有第一次测试环境缺少父目录/字体的运行失败已修复后重跑；最终完整结果见 brand-regression.xml。

未实现或未验收：自动光流/平面跟踪、OCR/商标检测评分、任意曲面或柔性包装变形、遮挡自动分割、反光/光照匹配，以及真实 Seedance 2.5 多次生成质量对照。用户提供的原始失败影片、品牌原件和对应请求可用于后续对照；本次没有为此发起付费请求。

透明标志无法清除视频中已有坏字；必须提供干净底片或完整标签贴片。正确透视会按物理视角改变形状，这与模型随意重画不同；本方案只保证使用同一原图及指定几何，最终定位正确性依赖轨迹与遮挡准确度。MP4 有损压缩也不支持像素级完全相同的宣传。
