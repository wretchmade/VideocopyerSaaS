# 合成优化实施记录

实施基准：`VIDEO-COMPOSITING-OPTIMIZATION-PLAN.md`。本记录独立于插件体验对齐验收；原 P4 的真实模型质量、两轮用户测试、剪映客户端实测仍待完成。本轮不调用付费供应商。

## 切片与安全条件

| 切片 | 内容 | 当前状态 |
|---|---|---|
| M0 | 固定素材与旧路线基准；全站单重任务槽、可重入资源租约、进程树采样与取消 | Windows 本地闭环完成；云端隔离与容量属 M5 |
| M1 | 确定性路线选择；普通视频/静态图层流式合成；v2 结果与按需最终成片审片；同版剪映 | 本地闭环完成 |
| M2 常用子集 | 原排版器静态字幕状态图、Logo、静态叠图；逐项质量门槛 | 已完成该子集；复杂效果未迁移 |
| 后续 | 复杂区间细化、有界自定义帧管线、片段缓存、浏览器编辑预览、云端容量 | 首批实测后决定 |

开始前无活动构建、任务或 Agent 轮次。回退快照 `.local/compositing-backups/20261020-160347` 共 2604 个文件；逐文件 SHA-256 与 SQLite online backup/integrity_check 已验证。原 commercial 指纹为 `f881e92fe2bc3da80d9eb3facfae1c7d9f051f795d2ffd5fe97c791df0aa89d5`。开发前已停止本项目服务，避免旧实现接受新构建。旧 identity、请求回执及交付不修改。

首轮保持 `libopenh264`、既有码率公式、yuv420p、48k 音频、尺寸、帧率、字体与 Pillow 排版器。新路径不通过降低规格换取性能。符合严格条件的原文件路线跳过重新编码；无法证明精确剪切/时间戳兼容时，不做 stream copy 猜测。

## 验证口径

使用已有生成素材与免费夹具，同机对照冻结的旧源码和新源码。分开记录素材准备、解码/合成/编码、完整解码验证、审片、剪映导出；采样整树 CPU/内存和临时盘，记录编码次数、图层状态缓存及回退原因。

先验证普通视频＋中文字幕＋透明 Logo＋配音，及只改字幕后的新交付；再覆盖坏素材、复杂回退、排队/运行中停止、Worker 重启、旧结果。支持范围按真实视觉/时间语义结果收敛。30% 时间、80% 临时盘、4GB 内存均为待测目标，本机不冒充 8C32G 云端容量。

## 参考边界

只读参考 Hypit-plus 的 layer-renderer 和 V0.6 验收记录，未修改该项目。借鉴透明状态图去重与共享时间线，不采用无条件 clean-base 二次编码、全长透明 MOV 或动画全画布 PNG 作为普通路径。

## 已实现的行为

- `render_plan.py` 在报价／构建中冻结计划版本、时间线形状、输出配置、资源规则及可解释的回退原因。普通源媒体解析后才确定实际路线。原文件／视频轨复用要求完整覆盖、相同尺寸与时钟、无视觉变化，并逐包验证呈现时间戳；不猜测关键帧剪切。
- `render_ffmpeg.py` 将普通视频剪辑、静态图层和音频编为同一滤镜图。每个静态状态由原 Pillow 字体排版器生成一次，按内容裁出 alpha 包围框，FFmpeg 缓存单张状态。普通合成只进行一次视频编码，没有 clean-base 二次编码或全片 PNG。
- 文本状态键包含样式、文本、字体／图片哈希、画布及排版实现；字幕修改只使相关文本状态失效。Logo 状态可复用。尚未实现合成片段缓存，修改字幕仍重新编码完整成片。
- 转场、组件、逐字字幕、动画／淡入淡出、品牌锁、透明 MOV、未验证的输入格式或时钟保留兼容路线。视频缩放先限定在 0.5–2 倍；范围外和分数像素 cover 裁切回退。原房间工程的交叉淡化属于兼容范围，不能用它宣称已取得普通路线的提速。
- v2 结果不伪造 `frame_hashes`。审片按成片哈希、解码器身份和帧号从最终电影解码、验证并缓存；v1 PNG 明确标记为编码前参考。现有构建、素材哈希和请求记录不改写。
- 剪映使用同一冻结工程。普通视频、图片和可原生表达的文字保留分轨；静态描边／阴影文字使用单张透明伴随图。逐帧品牌跟随仍用原伴随视频，禁止静态化。导出清单继续标注真实编辑器验收未完成。

## 资源与停止

全站使用 `DATA/resources` 下的单个 OS 文件锁，线程内嵌套操作复用同一租约。不能仅凭心跳超时抢占；接管前核对旧子进程 PID 与创建时间并等待退出。渲染、检查、按需取帧、浏览器采集、本地模型、媒体操作、剪映导出和 ZIP 打包共用准入。

默认 CPU 亲和限制为 4 个逻辑核；Windows Job 约束原生子进程树并在拥有者消失时关闭整树。流式路线的视频解码 2 线程、滤镜 2 线程，输入队列 4 帧、滤镜缓冲上限 64 帧，并限制同时输入数。内存采用子 Job 4GiB 硬上限与整树 RSS 50ms 看门狗；父 Python 分配是协作检查，不宣称是父进程的 OS 硬内存隔离。RSS 会重复计算共享页，CPU 亲和也不是整机所有后台服务的总 CPU 百分比承诺。Windows 资源约束已经实测，云端 cgroup／容器隔离尚未验收。

等待资源发生在 Web／核心写事务之外。停止通过独立流程 epoch 使等待和运行中的检查点失效，页面停止按钮也不受普通请求的忙碌状态阻塞。日志持续排入临时文件，避免管道背压；50ms 轮询在超过 16MB 时终止命令，阈值允许一次轮询间隔的短暂超量。失败或停止不提交 partial 成片／ZIP。未知远端请求仍遵循原账本核对流程，资源重试不授权重发供应商请求。

## 复现与回退

免费复现脚本：

```powershell
.venv/Scripts/python.exe scripts/compositing_benchmark.py --fixtures
.venv/Scripts/python.exe scripts/compositing_verify.py
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify.ps1
.venv/Scripts/python.exe scripts/compositing_repeats.py
.venv/Scripts/python.exe scripts/compositing_final_repeats.py
.venv/Scripts/python.exe scripts/compositing_report.py
.venv/Scripts/python.exe scripts/compositing_quality_suite.py
.venv/Scripts/python.exe scripts/parity_web_probe.py
.venv/Scripts/python.exe scripts/parity_history_audit.py
.venv/Scripts/python.exe scripts/compositing_service_check.py
```

基准输出必须使用新目录。不可并行跑多份渲染基准；测试样本的模型／供应商均为回环夹具。不要改用会调用付费供应商的旧 `browser-test.mjs`。

临时禁用快速路线时，在无活动工作、停止服务后设置 `D_RENDER_MODE=legacy` 并重启。保留新版结果读取器，不把旧 identity 改成新值，也不把旧代码直接覆盖到已经产生 v2 结果的数据库上。完整备份恢复仅用于明确的空闲切换点。

M3 复杂效果流式化、M4 区间缓存、M5 8C/32G 持续容量／并发压测仍未完成；真实模型规划质量、两轮用户验收、剪映实机打开编辑保存仍沿用原 P4 待验状态。

缩放质量同时比较最终成片之间的差异和相对于原 Pillow 未编码帧的保真度。最初只用两份有损成片相互 PSNR≥40dB 会把半尺寸样本（最低 38.07dB）判为失败；补查发现该样本对原始参考的 PSNR 为旧 23.6301dB、新 23.6316dB，属于不同编码误差而非新路线质量下降。因此采用双门槛：局部相互 PSNR≥35dB，且新路线对原参考的 PSNR 不得比旧路线降低 0.1dB 以上；切点和未缩放样本继续要求逐像素一致。测量与放大差分图保留在 `evidence/compositing/geometry/`，不把不同有损编码要求为文件哈希相同。

## 最终验证与实测

最终 commercial 代码指纹：`1773830532fde7dd52a259e2adcd43ae534ac1f3ab0e7ae1cf61403f6bd23b49`。

| 检查 | 结果与证据 |
|---|---|
| 合成与上游回归 | 60/60，通过真实 FFmpeg、取帧、几何／音轨、原生导出、停止／进程死亡／内存限制／租约丢失测试；[tests.xml](evidence/compositing/tests.xml) |
| 应用控制回归 | 42/42，含资源等待时全局停止仍可提交；[control-native.xml](evidence/parity/control-native.xml) |
| 真实 Codex／MCP／Chrome | 原模型名称不变，回环脚本模型与媒体服务；26 个脚本模型请求、7 个假生成提交；重启未重复提交、字幕修改新增生成 0；[web-protocol.json](evidence/parity/web-protocol.json) |
| 停止交互 | 本地后端确认 9ms；浏览器在报价请求未返回时仍能于约 44ms 发出停止；这是本地夹具结果，不是云端 SLA |
| 最终成片 | 720p、1080p、原房间兼容版、房间硬切派生夹具均与冻结旧版本成片 SHA-256 相同，全部关键帧一致、整片 SSIM 1.0；`evidence/compositing/quality-*/quality.json` |
| 缩放 | 0.5/0.75 倍、contain、整数 cover、2 倍通过双重保真门槛；0.25 倍明确回退；[geometry/quality.json](evidence/compositing/geometry/quality.json) |
| 旧数据 | 33 个数据库、7110 条原记录、1581 个历史文件、4 份交付核验通过，配置未变；[history-audit.json](evidence/parity/history-audit.json) |
| 恢复服务 | `http://127.0.0.1:8765` 就绪；4 份历史交付经 HTTP 流式读取复核哈希；[service.json](evidence/compositing/service.json) |

[完整重复基准](COMPOSITING-BENCHMARK.md)：同一台 20 逻辑 CPU／31.8GiB 本机，普通样本各 5 次，冷状态图缓存、顺序执行。12 秒 720p 中位数 **22.09→2.83s（-87.2%）**；60 秒 1080p **220.78→16.49s（-92.5%）**。普通路线临时盘降低超过 99.97%，1080p 峰值 RSS 268.5MB；同 1080p 来源与图层从 12 秒到 60 秒，峰值约 267.9→268.5MB。

性能回退也保留记录：原房间交叉淡化项目仍使用 PNG，在资源预算下由 **55.88→80.98s**（单次对照），没有改善临时盘。房间硬切派生夹具只用于复核已有真实素材和透明 UI 的流式画质，没有修改原工程，也不计入五次性能统计。后续优先迁移常用转场，再考虑区间缓存。

本轮付费供应商请求为 0。原供应商报价已到期，未自动续期或改动预算；已有素材的本地制作可用。真实供应商的新请求仍需要有效报价及既有用户授权流程。
