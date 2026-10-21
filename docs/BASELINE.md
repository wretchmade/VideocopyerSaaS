# 固定基线与边界

核验日期：2026-10-19。

官方 Codex 最新正式发行 **0.163.0**（2026-10-15 发布），tag `rust-v0.163.0`，tag object `129b8ec7ee6f4511557a4856279f529025c25af4`，commit `83086188ae0614bd882818ff1aa23f3194962012`。npm `@openai/codex` 固定为 0.163.0，平台二进制由官方包解析，package-lock 记录完整性摘要。未使用机器上的桌面 Codex 替代此固定版本。

证据：`evidence/codex-release.json`、`codex-tag.json`、`codex-commit.json`、固定二进制生成的 `codex-schema/`。协议 schema 使用 `codex app-server generate-json-schema --experimental` 导出。

来源：

- https://github.com/openai/codex/releases/tag/rust-v0.163.0
- https://github.com/openai/codex/tree/83086188ae0614bd882818ff1aa23f3194962012
- https://learn.chatgpt.com/docs/app-server
- https://developers.openai.com/blog/codex-as-a-platform

当前官方文档区分稳定 API 表面与需 experimentalApi opt-in 的能力；dynamicTools 及 item/tool/call 仍是实验 API。本版本明确 opt-in 并固定生成 schema。沿用本地 AgentRunner 隔离原则，使用私有 stdio，不暴露 App Server WebSocket。旧规格关于整个 App Server 的成熟度描述不作为当前全局结论，也不由本地验证推导公网生产支持。

规划模型按用户指定使用同一 Ark API 的 Seed 2.1 Pro：`doubao-seed-2-1-pro-260915`。官方模型表及 Responses 思考文档包含该 ID；本机实际完成的 Responses 调用及 Codex 工具调用是兼容性证据。调用经过本应用网关，禁用 Codex 自动 HTTP/stream 重试，移除未开放的工具，Flatten namespace 为 Ark 函数协议。模型回复未模拟。

- https://docs.volcengine.com/docs/ark/model-list?lang=en
- https://docs.volcengine.com/docs/ark/responses-api-deep-thinking?lang=zh
- https://docs.volcengine.com/docs/ark/model-pricing?lang=en&redirect=1

预算为用户本次明确授权 CNY 100。规划按保守上界 12/60 元每百万输入/输出 token 预留（不是声称账号结算价），输入使用 UTF-8 字节保守计数、输出强制 max_output_tokens。媒体每个最长 15 秒、720p 请求预留 33 元。实际 token/remote ID 与预留分开记录，实际账单未核对前 actual_micros 为 null。失败或中断可能已计费时保留额度。不得将此当作已对账钱包或供应商保证封顶产品。

D 源码来自用户指定 commercial-d 源码目录，87 个迁入文件及原始 SHA-256 见 `evidence/core-import.json`，不迁入插件 runtime 生成副本。历史 D5 状态、S3-R1/S4-R1 限定关闭以及来源接触事实保留于 `upstream-commercial/`。为了找到用户授权的配置来源，阅读过 VCtestplace 的 prepare_quote.py/runtime_bridge.py 及其引用的 Windows 凭据 helper；未导入、打包或运行旧 Hypit/videocopyer 运行时。新的凭据适配仅定向使用 Windows PasswordVault 公共 API，COS 使用腾讯官方 SDK。

控制层通过 SQLAlchemy 支持 PostgreSQL DSN；当前实测 SQLite WAL，事务 BEGIN IMMEDIATE 在 API/Worker 进程间串行化命令和预算。PostgreSQL 路径尚待部署实测。D 的执行仓库每项目独立 SQLite，不伪装为 SaaS。单用户 owner 固定由服务端建立；未来多用户需真正认证授权、沙箱、私有存储与迁移。

本机本地依赖：Python 3.12.14、Node 24.18.0、React 19.2.0、Vite 7.1.12、FastAPI 0.121.3、Pydantic 2.12.4；精确 Python/Node 依赖分别在 requirements.lock.txt、requirements-jianying.lock.txt、package-lock.json。剪映 serializer 独立 pyJianYingDraft 0.3.1 环境。FFmpeg 使用本机已安装的 LGPL shared 构建；不打包任何二进制或系统字体。来源目录保留第三方 NOTICE，发行许可事项 D5-20 未关闭。
