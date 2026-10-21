# VideoCopyer SaaS 代码审计（2026-10-21）

结论：当前版本是可运行的本地单用户视频制作原型，可作为源码基线上传；尚不满足公网多租户 SaaS 上线条件。审计覆盖 Web/API 边界、项目与文件归属、Agent 工具权限、预算与恢复、依赖、发布文件清单及已有离线回归。未执行付费生成、云部署或剪映实机验收。

## 尚未解决的发现

### P1：缺少用户认证与租户身份，不能用作公网服务

- 位置：`server/local/config.py:11`、`server/local/main.py:41`、`server/local/main.py:70`、`server/local/db.py`。
- `OWNER` 固定为 `local-owner`；API 使用 Host/Origin 校验和进程级 CSRF token。访问 bootstrap 即可获得写 token，项目列表没有用户登录前置条件。
- 当前启动脚本只监听 loopback，这是本地产品边界。若通过反向代理转发且重写 Host，所有访问者会共享同一 owner、项目及预算；Host/CSRF 校验不能替代身份验证。
- 上线前需增加登录会话、请求级租户身份、全 API/文件/事件流授权、租户化幂等键和配额，以及跨租户否定测试。不能简单将监听地址改成 `0.0.0.0`。

### P1：Python 锁定依赖仍命中公开漏洞公告

对两个根目录 Python 锁文件的 53 个唯一包版本查询 PyPI release JSON：52 项返回结果，1 项查询失败；7 个包名、8 个包版本命中公告。完整结果和公告链接见 [依赖审计 JSON](PYTHON-DEPENDENCY-AUDIT-2026-10-21.json)。公告别名有重复，不把条目数当作独立 CVE 数量。

| 包 | 当前版本 | 公告列出的后续修复版本上界 |
|---|---|---|
| certifi | 2026.10.18 | 2026.10.19 |
| Pillow | 12.1.1（主环境）、12.3.0（剪映环境） | 13.0.0 |
| python-multipart | 0.0.20 | 0.0.31 |
| Starlette | 0.50.0 | 1.3.1 |
| pytest | 8.4.2 | 9.0.3 |
| setuptools | 80.9.0 | 83.0.0 |
| wheel | 0.45.1 | 0.46.2 |

这些是公告给出的修复版本，并非本次已验证的新依赖组合。Pillow/Starlette 涉及主版本升级，需同时核对 FastAPI 约束、图像结果、上传解析与剪映序列化；本次保留现有 Python 基线，明确列为未修复。pytest/setuptools/wheel 属测试或构建工具，风险与运行时上传处理不同。numpy 2.5.4 查询出现 `URLError`，不能记作无漏洞。

代表公告：[Starlette Host 处理](https://github.com/advisories/GHSA-86qp-5c8j-p5mr)、[Pillow 解析递归](https://github.com/advisories/GHSA-p4wg-p73j-c528)。本应用的精确 Host 白名单缓解了前一项特定路径；依赖命中不等于所有漏洞均可被本应用利用，也不意味着整组漏洞已经缓解。

### P1（公网迁移前）：浏览器采集与媒体下载缺少网络出口隔离

- 位置：`server/app/workbench_d/commercial/browser.mjs:14`、`:22`，`server/app/workbench_d/commercial/providers.py:38`。
- 浏览器采集自动信任任务指定的初始 URL origin；下载器允许 HTTPS 目标以及 loopback HTTP。没有统一阻断私网、云元数据地址及 DNS 重绑定的服务端策略。
- 这是本地采集与离线 mock 所依赖的能力，但在共享云服务器上，用户/Agent 控制的 URL 或供应商输出 URL 可能触达内部服务。现有浏览器 origin 列表不等于服务端网络隔离。
- 云化时需限制出口并隔离 Worker/浏览器，显式区分本地测试入口和生产允许域名；此次未进行真实内网探测。

### P2：请求体限制执行得太晚，缺少总体上传配额

- 位置：`server/local/main.py:89`、`server/local/template_api.py:12`、`:84`、`server/local/gateway.py:27`。
- 文件大小检查发生在 multipart 解析之后；JSON/规划上下文在 `await request.body()` 完成后才检查长度。应用层 100 MB/2 MB/8 MB 限制不能约束之前的解析、缓冲或临时文件开销。
- 应在反向代理和 ASGI 接收层限制实际流量，同时限制文件数、并发、每租户存储量和资源保留时间。只检查 Content-Length 不足以覆盖分块上传。

### P2：模板资源验证失败后可能留下未登记文件

- 位置：`server/local/templates.py:52`、`:70`、`:217`、`:231`。
- `register_resource` 和 `stage_file` 先落盘，之后解码/探测；无效图片、视频或分析 JSON 抛错后没有统一清理新写入文件。不断提交不同无效内容可消耗磁盘，数据库列表也无法完整统计这些文件。
- 建议在受控临时目录验证，成功后原子发布；失败只清理本次新建文件，避免删掉已有并发共享资源。此项尚未修复。

## 本次已修复与发布整理

- Vite 从 7.1.12 固定升级为 7.3.7，同步 `package-lock.json`。升级前 npm audit 命中 1 个高危包、多个公告；升级后为 0。修复依据包括 [Windows 路径检查绕过公告](https://github.com/advisories/GHSA-587h-7wmj-h5pm)。
- 规划网关原先将供应商 `error.code` 原样写入账本并返回客户端。现在仅保留最多 100 字符的枚举式代码，拒绝含当前凭据的值，其余统一为 `provider_error`。新增 HTTP/账本集成回归、畸形错误值和跨项目 gateway token 拒绝测试。这不是对所有供应商输出的通用脱敏保证。
- 默认 `scripts/verify.ps1` 加入模板和安全回归，测试报告写入 `.local/verification.xml`，避免依赖未分发的历史证据目录。
- `.gitignore` 排除环境配置、数据库、虚拟环境、缓存、日志、密钥文件、编译产物及 `docs/**/evidence/`；仅保留 `docs/evidence/codex-LICENSE`。这些文件仍留在本机，未删除业务数据。
- 新增 `scripts/check_publish.py`，检查实际暂存内容中的私有运行文件、常见密钥格式、签名 URL、带密码的 URL 与超过 10 MiB 的文件。扫描只显示路径、行号和规则名。规则扫描是启发式检查，不保证发现任意格式的密钥。
- README 明确首次安装步骤、未上线边界和历史证据不随源码分发的事实；保留上游来源与第三方许可说明，没有为项目擅自指定开源许可证。

## 验证

| 检查 | 结果与边界 |
|---|---|
| 默认控制/恢复/工作流/工具/模板/安全回归 | 85 项通过；本地隔离数据，未请求付费供应商 |
| 合成与上游限定回归 | 60 项通过；真实本机 FFmpeg/字体/剪映序列化依赖，未验证剪映 UI |
| 工作流图 | 3 组语义断言通过；32/152/302 节点布局测量通过 |
| TypeScript 与 Vite 生产构建 | 通过 |
| npm audit | 修复后 0 个已知漏洞包 |
| 两个 Python 环境 pip check | 均通过；只证明依赖约束一致，不证明安全 |
| Python 漏洞元数据查询 | 7 个包名仍命中；numpy 查询未完成；详见 JSON |
| 暂存发布扫描 | 未发现规则匹配的敏感项；另行检查的长凭据字面量仅命中安全测试假密钥 |

运行期间存在 Starlette/AnyIO 和 Pillow 弃用警告，尚未造成回归失败。未把历史测试记录当作本次结果；未执行付费浏览器脚本。没有复验 PostgreSQL、云对象存储、真实供应商故障恢复、跨机安装和用户剪映编辑流程。

## 复现

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
.venv/Scripts/python.exe scripts/compositing_verify.py
npm audit --json
.venv/Scripts/python.exe -m pip check
.venv-jianying/Scripts/python.exe -m pip check
# git add 完成后、commit 前运行；空暂存区会返回失败。
.venv/Scripts/python.exe scripts/check_publish.py
```

合成检查依赖自己机器的 `config.local.json`、FFmpeg/FFprobe 和字体；历史工程、媒体与凭据不包含在仓库内。源码上传与公网服务发布是两个独立阶段，本报告不构成上线验收。
