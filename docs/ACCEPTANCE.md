# v0.1 开发者验证记录

日期：2026-10-19。应用地址 http://127.0.0.1:8765 ，启动命令见 README。

## 通过的主链路

- 官方 Codex 0.163.0 → 本应用私有 stdio Bridge → 受控 Responses 网关 → 用户指定 Ark Seed 2.1 Pro。真实工具调用、流式回答、规划保存，未固定回答。
- 首页创建项目、初始文本/附件保留、专属路由；刷新和项目切换；选中分镜并通过对话改字幕。
- 实际 Seedance 请求 `cgt-20261019163133-82wzz` 与 `cgt-20261019163428-dz9bb` 均成功，每个返回 108900 total tokens。生成内容为“清晨花店”2 个 5 秒镜头，非固定演示视频。模型效果仍需用户审片。
- 真实 FFmpeg 合成为 10 秒 MP4，浏览器实际播放；从同一构建生成可编辑多轨剪映 ZIP。
- 对话只改第一个镜头字幕，规划 revision 1 → 2，两个已生成视频实际复用，报价 paid_tasks=0；新版成片生成，旧版保留。
- COS 真实上传一个视频素材并通过对象长度校验，凭据仅在后端。参考图当前通过 Ark 的内联协议传递，COS 是可选受控备份适配器；未假称所有素材均通过 COS 生成。
- 重启服务恢复持久会话；等待澄清时刷新、停止、继续；未额外提交媒体请求。
- 本地上传测试图片、测试音轨与字幕的实际渲染/导出通过；ZIP 有独立 video/image/text/audio 轨。测试音轨用于加工验证，不代表 TTS 模型效果。
- ZIP 下载 SHA-256 校验；安装到新目录且不覆盖；素材路径重写后不再引用旧执行目录。安装回执更新 native/document/file 哈希。

## 自动化证据

| 证据 | 范围 |
|---|---|
| `evidence/control-tests.xml` | 12 项：创建去重、命令冲突、不可变修订、跨项目文件访问、Host/Origin/写接口、并发预算、版本绑定、损坏素材拒绝、未知提交不重复、路径越界/覆盖拒绝 |
| `evidence/upstream-regression.xml` | 21 项限定上游回归：保留样本/原生时序、过期报价恢复、未知提交不重付；15 项非本次筛选用例未运行 |
| `evidence/browser-*.png` | 真实网页首页、规划、预算、执行、交付、COS、改版、窄屏、澄清 |
| `evidence/real-delivery.json` | 首个真实交付的项目/版本/构建/产物与用量 |
| `evidence/revision-verification.json` | 修订 2、素材复用、0 新媒体请求、旧交付保留 |
| `evidence/conversation-recovery.json` | 刷新澄清、停止、官方 thread/resume、同一远程请求标识 |
| `evidence/attachment-verification.json` | 首条文本与附件、刷新保留、项目隔离；修复后复验通过 |
| `evidence/final-delivery.json` | 安装脚本修复后的新包装交付、重复导出去重、ZIP 下载哈希、新目录安装 |
| `evidence/paid-media-requests.json` | 远程请求标识、模型、成功状态与真实 token 用量，无凭据/签名 URL |
| `evidence/media-runtime.json` | 实际 LGPL FFmpeg/FFprobe 版本、配置、二进制哈希 |

前端 TypeScript/Vite 构建通过；浏览器通过用例无 pageerror。Python 测试存在上游 Starlette/AnyIO 弃用警告，不影响结果。

最终本机检查：服务重启后可访问；同一远程请求 GET 返回 succeeded；MP4 与 ZIP 再次下载哈希一致；87 个迁入文件哈希保持原样；`pip check` 通过。最终预留累计 **CNY 78.839572 / 100**，不是实际扣费金额。记录见 `evidence/final-verification.json`。

修订 2 有两个导出包装：最初 ZIP，以及安装器哈希修复后的新 ZIP。它们绑定同一成片构建，旧包没有被覆盖；最新交付 ID `24d300f8d299b415ca69f900eb7c6ba9`。重复不同命令 ID 导出也返回此已有包装，不会改写原文件。

## 不计为通过

工作流布局 v2：用户进一步指出第一版连线混乱，现按真实依赖与镜头行重构。当前布局证据为 `workflow-lanes-full.png`、`workflow-lanes-desktop.png`、`workflow-lanes-empty.png`、`workflow-lanes-mobile.png`；此前 `workflow-full-canvas.png` 等仅作为迭代历史。纯图逻辑和浏览器同步/性能数据分别见 `workflow-graph-tests.json`、更新后的 `workflow-browser.json`。模拟规模测试与真实双镜头播放分别记录，不混称真实模型制作验收。新版仍待用户视觉复验。

2026-10-19 工作流修正：用户指出原标签页 UI 是体验退化，该版 UI 不计为用户认可。统一画布替换后的开发者验证见 `evidence/workflow-control-tests.xml`（16 项，含 4 项素材归属回归）和 `evidence/workflow-browser.json`（真实素材播放/版本连线、选中联动、拖动/缩放持久化、折叠/平移/重置、专注模式与弹窗、空项目、390px 窄屏）。`workflow-desktop.png`、`workflow-full-canvas.png`、`workflow-empty.png`、`workflow-mobile.png` 为更新截图；浏览器未发写请求、无 pageerror、预算预留未增加。仍待用户对新版画布复验。

目标剪映实际打开、编辑、保存、重开尚未完成；未收到版本与草稿目录，常见默认安装位置也未发现目标安装。多轨结构/重定位通过不能替代此项。请按 USER-TESTS.md 完成两轮用户测试并记录实际剪映版本。

供应商费用实际对账未完成，预留与 token 不是最终账单。真实供应商取消/未知提交故障注入未做；只有受控协议回归。POST 未知结果不会自动重试，远程状态可在停止后单独查询，人工核对接口要求同账户/模型确认的请求 ID。

PostgreSQL 未运行实测；当前实际控制库为 SQLite WAL，执行库为每项目 D SQLite。跨机环境安装、二进制/字体发行许可、复杂效果、3D、其他模型与语音生成保持原 D5 缺口。未公开发布，不具备多用户收费上线结论。
