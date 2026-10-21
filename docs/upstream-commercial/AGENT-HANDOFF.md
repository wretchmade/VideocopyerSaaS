# 后续 Agent 接手入口

## 1. 先确认你在维护哪个版本

- 当前：**D 2.0.0-beta.1**，第五阶段成型包，独立核心。
- 新开发工作根：本文件所在 `docs/commercial` 向上两级，即 `commercial-d`。本次机器绝对路径：`C:/Users/Administrator/.codex/worktrees/929d/VideoCopyer/commercial-d`。
- 迁入源：`C:/Users/Administrator/.codex/worktrees/531f/VideoCopyer` 的 `2.0.0-dev.2` 独立实现；来源记录 `evidence/stage5-source-import.json`。该树包含历史原型，不把整树当分发闭包。
- 外层 `929d/VideoCopyer/plugins/workbench-d` 是旧历史版本，不能用它覆盖当前插件。当前插件在 **commercial-d/plugins/workbench-d**。
- 第三、四阶段仍为 PARTIAL；第五阶段交付不将模型、3D 和剪映实机自动标为通过。

## 2. 阅读顺序

1. 本文、项目 `AGENTS.md`。
2. `DEVELOPMENT-BACKLOG.md`：D5-01～D5-20，现状、入口、实施范围、依赖和验收。
3. `total-matrix.md`、`stage5.md`、`evidence/stage5-verification.json`。
4. 需要某项历史背景时，再读 `stage3.md`、`stage4.md`、`provenance.md` 和对应证据。旧证据中的绝对路径属于当时机器，不能假设换机后存在。

基线 ZIP 哈希在待开发文档；基线二进制不随本包分发。先按哈希确认版本，不用已安装的 0.3.x 缓存替代。源码接触事实按原记录保留，不许改写为未经接触的洁净室声明。

## 3. 源码地图

| 路径 | 内容 |
|---|---|
| `services/api/app/workbench_d/commercial/schema.py` | D Project、帧/素材/任务合同 |
| `engine.py / store.py / worker.py / processes.py`（同目录） | 修订、数据库、任务执行/恢复、进程树 |
| `render.py / typography.py / transitions.py` | 图像帧、文字、转场和音频合成 |
| `providers.py / provider_contracts.py / ledger.py` | 服务商、请求账本与预算 |
| `speech.py / model_driver.py / media.py / storage.py` | 本地模型、加工和存储 |
| `components.py / capture.py / browser.mjs` | 参数组件与浏览器采集 |
| `production_state.py / review_copy.py` | 画布、反馈、归档和复用 |
| `drafts.py / jianying_codec.py / native_import.py` | 草稿和可选剪映序列化 |
| `api.py / stage4_api.py / mcp.py` | HTTP/MCP 共用操作合同 |
| `apps/web/src/pages/workbench-d/ProductionProjects.tsx` | 项目/任务/渲染界面 |
| `apps/web/src/pages/workbench-d/ProductionStudio.tsx` | 画布/审片/工作流/草稿界面 |
| `plugins/workbench-d/scripts` | 安装配置、运行和环境诊断 |
| `scripts/build_d_core.py / package_stage5.py` | 白名单 staging 与两种 ZIP |
| `services/api/tests/test_d_*.py` | 核心、模型协议、组件、草稿及时序回归 |

`plugins/workbench-d/runtime`、工具 schema 引用和插件内 docs 为生成副本。修改源文件后构建；不要只修改生成副本。工具 schema 构建时从实际实现生成，新增工具需同步客户端与测试。

## 4. 配置与运行

按 `plugins/workbench-d/README.md` 设置 Python 3.12、核心依赖及 FFmpeg。可选剪映环境独立安装，不混入核心。模型/浏览器/存储各自可选；没有模型权重不影响本地图形演示。

默认外部配置 `%LOCALAPPDATA%/WorkbenchD/runtime.json`，默认数据目录同级 `data`。测试必须指定自己的 `D_CONFIG_FILE`、`D_CORE_DATA`，不要读取用户生产数据。设置文件只保存路径和环境变量引用，凭据不得进入仓库/ZIP。

## 5. 构建

在 `commercial-d` 根运行，python 指向已配置的核心环境：

```powershell
python scripts/package_stage5.py
```

输出在 `artifacts/distribution/`。插件包含已构建工作台，修改前端时先重建：

```powershell
Set-Location apps/web
npm ci
npm run build:d
Set-Location ../..
python scripts/package_stage5.py
```

前端 lock 保留前阶段开发工具版本；部分未使用开发依赖不进入插件 JS，后续可按实际依赖裁剪 lock 并重新验证。本项目的 build/build:d 均只构建 D。不要运行外层旧 `package_plugins.py`。

`build-manifest.json` 记录每个插件文件哈希；两次 ZIP 输出哈希必须一致。最终校验和见输出的 SHA256SUMS，不将最终 ZIP 哈希写入 ZIP 自身制造自引用。

## 6. 测试与验收

先用干净核心环境安装测试依赖（已有环境可跳过）：`python -m pip install pytest httpx`。以下路径值由本机实际环境提供，不能照抄旧路径：

```powershell
$env:PYTHONPATH = (Resolve-Path services/api).Path
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:D_FFMPEG = 'C:/reviewed-media/bin/ffmpeg.exe'
$env:D_FFPROBE = 'C:/reviewed-media/bin/ffprobe.exe'
$env:D_TEST_FONT = 'C:/reviewed-fonts/NotoSansSC.ttf'
$env:D_JIANYING_PYTHON = 'C:/d-jianying/Scripts/python.exe'
$env:D_NODE = 'C:/node/node.exe'
$env:D_PLAYWRIGHT_MODULE = 'C:/browser-runtime/node_modules/playwright'
$env:PLAYWRIGHT_BROWSERS_PATH = 'C:/browser-runtime/browsers'
New-Item -ItemType Directory -Path artifacts -Force | Out-Null
python -m pytest services/api/tests -q --basetemp artifacts/test-run --junitxml docs/commercial/evidence/latest-tests.xml
```

上述全套包括实际媒体与浏览器、可选草稿，缺依赖会失败；应配置依赖或明确记录未测，不能静默跳过并写全通过。历史 `test_d_core.ps1` 等脚本含旧机路径，优先用此处可配置命令。

打包后另解压至新目录，设置 `D_REVIEW_PLUGIN_DIR` 为解压后的 `workbench-d`，运行 `python scripts/verify_d_core_clean.py`。该脚本要求核心环境不含旧 SQLAlchemy 依赖，验证真实 MCP、任务重启、去重、取消、交付、审片、工作流、草稿结构。另用 `scripts/verify_stage5_package.py` 验证包内 manifest 启动器与本地工作台/演示；参数见 `--help`。

UI 行为验证脚本 `scripts/verify_d_core_ui.mjs` 需要 19449 端口和相应测试数据/字体路径；它保留历史验证用途，执行前检查其环境假设。当前包 HTTP 静态资源与浏览器验证记录在 stage5 evidence。

## 7. 必须保持的边界

- 不把服务商模型库存当作可用服务清单，21 适配/40 受阻不是 61 个已测模型。
- 修订不可变，命令幂等；素材哈希明确；预算不跨修订继承；未知远程提交先对账，不重复付费。
- 原生效果与局部烘焙分别报告；明确拒绝的操作仍是缺口，不能删错误检查假装支持。
- 保留 S3-R1 远程恢复及 S4-R1 每帧/样本回归；不能仅对比首尾帧。
- 只读观察/独立功能规格与开发来源如实记录；不引入 Hypit 运行时、上游技能或源码转写替代。
- 不把协议模拟、文件结构、本地配置成功写成真实模型效果、剪映 UI 或 Codex 安装成功。

## 8. 交接给下一任的要求

每次接续只按用户范围推进，使用 D5 固定 ID；更新状态/证据和未决依赖。文档里的待办不构成付费、公开发布或全局安装授权。不要把模型账户和预算问题变成代码已完成的借口，也不要为缺环境捏造结果。

如只拿到插件 ZIP，可运行当前功能；如要开发，请同时取 source-handoff ZIP。报告中提供新包路径、校验和、验证结果和剩余任务，不要求后续 Agent 从对话猜测源码位置。
