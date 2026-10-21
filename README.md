# VideoCopyer SaaS · 本地单用户原型 v0.1

可本地启动的单用户视频制作应用：网页 Codex 会话、人物/分镜画布、附件、不可变规划、持久任务、预算门禁、真实 Ark 素材制作、MP4 与可编辑剪映 ZIP 成对交付。开发范围和未决项见 [开发状态](docs/DEVELOPMENT.md) 与 [验收记录](docs/ACCEPTANCE.md)。

当前源码尚未实现多用户登录、租户隔离与线上计费，不应直接接入公网。审计结果、已修复问题和验证范围见 [代码审计](docs/CODE-AUDIT-2026-10-21.md)。

仓库仅包含源码、配置模板与文档。`config.local.json`、`.local/`、环境文件、数据库、构建产物及历史执行证据均保留在本机，不随 Git 上传；`docs/evidence/` 中仅保留 Codex 许可证。历史文档指向的本机截图和运行证据不会出现在新克隆中，需在自己的环境重新验证。

## 在本机启动

完成下方首次安装并配置本机参数后，在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start.ps1
```

访问 **http://127.0.0.1:8765**。服务只监听 loopback。默认后台运行且不弹终端；`-Foreground` 在当前终端运行，`-NoBuild` 跳过前端构建。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/stop.ps1
.venv/Scripts/python.exe scripts/doctor.py
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

停止脚本只终止记录匹配的本项目进程树。关闭页面不会重新提交远程生成请求，未知提交保留为待核对。

首次安装或换机器：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -Python "C:\Path\To\Python312\python.exe"
```

要求 Python 3.12、Node 22+、经过核验的 LGPL FFmpeg/FFprobe，以及可用中文字体。独立剪映序列化环境由 setup 创建。锁文件为 `requirements.lock.txt`、`requirements-jianying.lock.txt`、`package-lock.json`。系统字体和 FFmpeg 二进制不随源码分发。

## 配置与数据

- `config.local.json`：本机服务配置，已被 gitignore 排除；模板为 `config.example.json`。只保存配置路径、模型 ID 和凭据引用。
- 规划、媒体与 COS 需使用自己的供应商配置与凭据引用；示例配置不包含密钥。Windows PasswordVault 需在实际用户账户下读取。
- 总测试上限 CNY 100，文本、媒体和 COS 都有持久预留记录。实际供应商账单未核对前 actual_micros 为 null，未知请求保留预算且禁止自动重发，不等同充值钱包。
- 默认数据 `.local/data/`：控制数据库、附件、独立 Codex 会话、每项目 D 执行库和交付。停止服务后备份整个目录。
- `VC_CONFIG` 选择配置文件，`VC_DATA` 选择数据根，`VC_DATABASE_URL` 可配置 PostgreSQL DSN，例如 `postgresql+psycopg://user:password@127.0.0.1:5432/videocopyer`。当前实测 SQLite WAL；PostgreSQL 路径待环境实测。本机不依赖 Docker。

官方 Codex 固定为 **0.163.0**。tag、commit、协议和来源见 [固定基线](docs/BASELINE.md)。浏览器只连接应用 API，App Server 通过后端私有 stdio 运行。未复用个人 Codex 登录，未暴露通用终端或平台密钥。

## 使用

1. 首页输入需求，可附图片、视频、音频或文本，自动进入专属项目。
2. Codex 使用原 D Skill 和完整 43 个 D 工具创建原生工程；右侧在执行前展示素材、生成任务、图层、音轨、转场与合成依赖。选中节点后在对话中修改。
3. 查看当前修订的新增、复用、重做范围与增量报价。点击报价卡，或发送“确认报价 ID”（唯一待确认报价也可说“确认制作”）。后台完成会回到 Agent 检查、审片和交付。
4. 说“全部先停”或点击“全局停止”，会停止当前项目整个流程。修改 B 后可复用有效 A/C；再确认新范围才恢复。说“B 提示词不变，再生成一次”可强制重生成；只改字幕不会新增生成请求。
5. 成片与剪映工程绑定同一构建，旧版本继续可下载。旧项目仍显示原画布；首次原生编辑通过对话明确选择旧任务，使用 `adopt_legacy_revision` 接管来源。上传视频可以指定帧检查；本地剪映目录和旧 D 工作区通过明确来源授权后导入。
6. ZIP 包含新目录安装脚本、素材、原生草稿、哈希和限制说明。关闭剪映后按说明安装到新草稿目录，不覆盖已有工程。

剪映 ZIP 保留支持范围内的视频、图片、字幕和音轨，并排除中间帧。**目标剪映打开→编辑→保存→重开尚待用户实机验收**，结构/重定位通过不能替代实机通过。复杂效果、3D 和语音生成模型等仍按原 D 的实际能力和配置边界处理。

[对齐实施记录](docs/PARITY-IMPLEMENTATION.md) 和 [43 项能力矩阵](docs/PARITY-CAPABILITIES.md) 区分本地通过证据与待验项。完整非付费端到端脚本为 `scripts/parity_web_probe.py`，使用本地模拟 Responses/媒体供应商、真实 Codex/MCP/FFmpeg/Chrome，不验证真实模型规划质量。原供应商配置不会因重启自动刷新；固定报价到期后需运营方更新，不能用过期报价继续生成。

[两轮用户测试清单](docs/USER-TESTS.md) 可直接用于反馈。`browser-test.mjs` 会创建项目并发起付费素材制作，不是免费 CI；`scripts/verify.ps1` 只做非付费验证。

`node scripts/workflow-browser-test.mjs` 对本机已有样例做只读画布回归，阻止所有写请求并核对测试预算未增加；样例项目 ID 写在脚本中，换机器需使用对应样例数据。画布交互和截图证据见 `docs/evidence/workflow-browser.json` 与 `workflow-*.png`。

`npm run test:workflow` 验证确定性布局、连线避开卡片、复用语义和结构失效规则。浏览器脚本还使用明确的合成快照测试 32/152/302 个节点的状态更新，不写入项目数据库。[布局与同步说明](docs/WORKFLOW-LAYOUT.md) 记录测量范围和当前边界。

## 源码地图

| 位置 | 内容 |
|---|---|
| `web/` | React 双栏工作台和项目路由 |
| `server/local/` | API、控制存储、Codex Bridge、计量网关、Worker、D 适配、COS |
| `server/app/workbench_d/commercial/` | 用户指定的 D 独立核心迁入源码 |
| `scripts/` | 启停/诊断、草稿重定位、浏览器验证 |
| `tests/` | 数据正确性与上游限定回归 |
| `docs/evidence/` | 来源、运行证据、截图、测试结果和哈希 |

上游源工作树和已安装插件未修改。S3-R1/S4-R1 限定关闭及 D5 待办保留。本地两轮测试通过也不代表公开多用户收费上线完成。
