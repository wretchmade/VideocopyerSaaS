# 阶段二修复与阶段三工程交付

2026-10-16。后续独立审查已接受 R1/R2 的限定测试范围，阶段三为 PARTIAL，并提出 S3-R1、S3-G1、S3-G2。第四阶段当前修复、测试与缺口见 [stage4.md](stage4.md) 和 [总矩阵](total-matrix.md)。下文保留第三阶段交付记录；没有付费调用、发送生产素材、下载模型权重、发布插件或安装市场。

## R1 / R2

- **R1**：新增显式 `transitions`。crossfade 在预乘 alpha 空间混合后一次合成，11 帧的红绿中点现在精确为 `(128,128,0,255)`。普通两个图层各自 `fade_in/fade_out` 仍为正常 source-over，原 `(64,128,0,255)` 语义保留，不能再称作交叉淡化。图像、实际 PNG 编码视频和色块分别测试。参与图层必须在堆叠顺序中相邻，拒绝同层冲突或叠加 fade。wipe/push 也是独立过渡类型。
- **R2**：字体回退形成字体 run，所有 run 共用基线；使用 ascent/descent 排下一行，前景、描边、阴影共用同一布局。高亮只改变着色，不拆分字体测量，避免 kerning 随高亮跳动。`Agpyj ABC` 与同字体整串 Pillow 参考逐像素一致；混排、强制字体回退、换行、高亮、描边和阴影有额外回归。没有放宽旧审查容差。
- 原独立审查截图、JSON、原 render SHA 原样复制至 `artifacts/d-commercial/stage3-review/before-*`；不执行会向审查源目录写入的原复现脚本。新结果在同目录 `caption-before-after.png`（上：原审查；下：新结果；每行左侧均为参考）及 `after-crossfade.png`。机器证据：`evidence/stage3-effects.json`。

## 本轮落地范围

| 项目 | 新实现与真实接入 | 已验证 | 未验证或未实现的范围 |
|---|---|---|---|
| A07 语音 | `speech.py` 独立进程契约；`model_driver.py` 通过公开接口接 Kokoro TTS、WhisperX ASR/纠正文稿声学对齐、独立 Seed-VC CLI；源音频哈希、16k 证据哈希、样本域词边界、wordId、missing；transcript 任务产物能驱动实际字幕；音轨仍使用 48k 样本域混音 | 纠正词串、缺失边界、字幕高亮、独立进程/Seed-VC CLI 协议夹具、真实 WAV 裁切淡化及已有混音测试 | 没有安装这些模型环境和权重；语音可懂度、音色相似度、真实 ASR/对齐误差未测。协议夹具复制测试音频，不是模型效果。缺失词时间不会伪造，字幕生成要求先纠正 |
| A08 模型 | `providers.py`、`provider_contracts.py`、`ledger.py`；精确基线 61 个 provider/model 行与 5 个本地替代入口的矩阵；显式 wire 字段、参考角色、inline/upload/storage、异步轮询、结果集落盘、错误、取消请求、报价过期检查 | 本地 HTTP 模拟服务真实 POST/GET/DELETE、两份产物下载和哈希、提交断线、确认远端 ID 后恢复、并发预算和 dispatch fencing；Beat/Ark/Pollo 参考编码断言 | 61 行是完整追踪清单，不是 61 个服务实测。HiAPI/Monid/HypiHub、TokenDance H3 等需补齐并固定当前/鉴权接口合同，默认阻止执行；服务端当前可用性、全部模型参数限制、实时计价及真实取消均未验。没有 OAuth refresh 实现 |
| A09 媒体 | `media.py`：图像变换/合成、可调软边色键、视频变换/色键透明、精确帧抽取、转换、音频处理；`model_driver.py` 可接 rembg 和 RVM TorchScript，RVM 四个递归状态跨帧保留 | 真 PNG 边界透明、运动视频每帧位置与 alpha、实际 MOV/WAV 编解码、DAG 产物再进合成 | 色键不是语义抠像。rembg/RVM 未有权重，因此发丝、遮挡、复杂背景和运动抠像质量未验；RVM 适配器按源名义帧率规范化，未提供 VFR 原始 PTS 保留 |
| A10 组件 | `components.py` 15 类参数化场景、11 类帧效果；共享图层变换/显式转场；可在 D UI 添加并编辑参数，成片来自同一 rasterizer | 所有 26 类真实帧、动态变化、各场景画面差异、编码排行榜片段；接触表与帧哈希 | 这是独立首版组件，不等同原模板的全部参数/动作/资产。尚无完整脚本化组件动画编排、3D 材质/骨骼动画和全部高级文字塑形 |
| A11 扩展 | 独立 Ranking、LastWar、LastWarHybrid、ModelOverlay 场景；LastWar 使用自有网格/单位/位置/血量参数，混合层和模型叠加接受显式图片或视频素材；Seedance/Seedream 经独立 Ark 契约 | 同一 D Project、实际帧、alpha、关键帧及成片；没有引入原扩展实现或素材 | ModelOverlay 是 2D 媒体叠加，不是 GLB/FBX 3D 加载器。Last War 玩法/物理/复杂原场景的视觉等价未验；不得称为全量复刻 |
| 支撑能力 | 预算绑定 project/revision/account/currency；微货币整数、并发原子预留；存储为内容寻址 local 和 COS presigned signer 契约；MCP/HTTP/UI/DAG/恢复同入口 | 同预算并发仅一次 admission、同请求仅一次 dispatch；错账号/币种/修订拒绝；本地媒体和远程模拟结果进入实际渲染 | 总预留是保守账本；服务商无硬支出上限时不能保证账单不超过估价。暂未自动结算/释放实际差额。COS 未用真实账号上传，签名服务由部署方提供；完整工作流复用仍延后 |

组件：TierBoard、Column、TopThree、DepthCard、Comment、Quiz、Chat、Explainer、TalkingHead、RichText、PathText、Ranking、LastWar、LastWarHybrid、ModelOverlay。效果：Flash、ColorWash、Vignette、ScanLines、DirectionalMatte、WhipVeil、GlitchVeil、Grain、LightLeak、Bokeh、TVStatic。

## 远程请求恢复语义

`prepared → submitting` 在任何引用上传或生成 POST 前提交 SQLite FULL 事务。稳定 requestId 来源于 build+task，Idempotency-Key 仅作为服务商额外保护，系统不依赖服务商一定实现它。POST 成功保存 remoteId 后只恢复 GET；提交断线或进程中止时，`submitting/unknown` 没有 remoteId 就拒绝自动重发。`d_reconcile_request` 接受用户核实的远端 ID，恢复轮询。未知请求保留预算；取消 ACK 仅表示请求发出，不伪装成退款或远端已终止。

`d_authorize_budget` 对已保存的精确修订授权；任务 `budget` 可省略以选择该修订/账号/币种最新 grant，避免“添加 budgetId 导致修订改变”的循环。新修订不继承旧授权。`max_cost_micros` 必须为正，且至少覆盖未过期 quote 的 upperMicros。预留/并发约束按 grant 生效，不是跨所有授权的全账号支出策略。

## 运行配置

工程不保存密钥。`D_PROVIDERS`、`D_MODEL_ADAPTERS`、`D_STORAGE` 是部署方配置文件路径；文件哈希进入冻结 runtime identity。密钥仅由配置的 `credential_env` 引用。报价为部署方固定的上界估计，`expires` 是 Unix 秒；不伪装成服务实时价。所有请求必须 HTTPS，测试仅允许 loopback HTTP；带认证请求不自动跟随重定向，产物下载不带服务商密钥。

`D_PROVIDERS` 最小配置形状（值必须由部署方核实，示例过期时间 0 会阻止请求）：

```json
{
  "ark.account": {
    "service": "ark",
    "base_url": "https://ark.cn-beijing.volces.com",
    "account": "EXPLICIT_ACCOUNT",
    "currency": "CNY",
    "credential_env": "D_ARK_KEY",
    "models": {
      "EXPLICIT_ENDPOINT_OR_MODEL": {
        "output_kind": "video",
        "quote": {"upperMicros": 0, "expires": 0}
      }
    }
  }
}
```

`D_MODEL_ADAPTERS` 每个条目含 `python`、`script`、`script_sha256`、`license`、`operations`、`weights`（每项 name/path/sha256/license）和 `settings`。单独环境显式安装依赖；本插件不安装/下载模型。内置 runner 的权重名：TTS=config/model/voice；Seed-VC=entry/model/config；rembg/RVM=model。WhisperX 的 settings 需要本地 `asr_directory`、`alignment_directory`，权重文件仍逐个登记。语言、device、compute_type 由 settings/任务显式配置。`model_driver.py` 是独立适配器代码，外部模型本体不随插件分发。

`D_STORAGE` 可配置 `{"local":{"kind":"local","root":"..."}}`；COS 配置为 `kind: cos-presigned`、`signer_url`、`credential_env`。签名服务接受 key/sha256/bytes，返回 put_url/get_url/headers；D 执行 PUT。真实 COS IAM、过期与权限策略需部署方验收。

## 证据与复现

- `scripts/test_d_core.ps1`：35 项（原核心 21 项、新增 14 项），包含真实 FFmpeg、浏览器及模型协议模拟；`evidence/core-tests.xml`。
- `scripts/verify_d_core_clean.py`：最新 staged MCP 在干净 Python 环境创建/编辑/校验/渲染/重启/去重/取消/交付；`evidence/clean-package.json`。
- `scripts/verify_d_stage3_ui.ps1`：真实 UI 添加 ColorWash 与 image-transform 任务，将任务产物放入图层，保存/渲染/预览/视频播放/下载，440px 无溢出；`evidence/ui.json`。
- `scripts/record_d_stage3_evidence.py`：只读旧审查，生成 R1/R2 前后证据及 `evidence/provider-model-matrix.json`；不调用原模型。
- 26 类组件接触表：`artifacts/d-commercial/pytest/test_every_component_and_effec0/components-contact.png`；同目录 `components.json` 和 `encoded/output.mp4`。

## 来源与许可边界

本轮只读原精确版本的包元数据、公开 README 输入/输出合同及独立审查结果，没有导入原 provider/component/model 实现。公开服务合同参见 [Ark 视频](https://docs.volcengine.com/docs/ark/create-video-generation-task-api)、[Ark 图片](https://docs.volcengine.com/docs/ark/image-generation-api)、[BeatAPI](https://docs.beatapi.io/quick-guide)、[Pollo](https://docs.pollo.ai)、[HiAPI 模型索引](https://www.hiapi.ai/docs/models.json)。HiAPI 索引本次浏览无法读取；Monid schema 需要账号 inspect，未用推断冒充已核实合同。

模型适配参考 [WhisperX](https://github.com/m-bain/whisperX)、[Seed-VC](https://github.com/Plachtaa/seed-vc)、[Kokoro](https://github.com/hexgrad/kokoro)、[rembg](https://github.com/danielgatis/rembg)、[RVM](https://github.com/PeterL1n/RobustVideoMatting)。这些是外部依赖；Seed-VC 和 RVM 上游代码为 GPL-3.0，单独进程并不自动消除发行义务。实际权重、语料、声音/人脸素材及部署方式必须各自审核。没有法律洁净室或商业分发许可已清理的结论。

完整分组画布、工作流体系、审片反馈和剪映迁移保持原延期边界。当前证据允许复核本轮实现，不应据此直接认定 A07—A11 全量验收通过。
