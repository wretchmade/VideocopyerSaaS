# Native harness 改进执行计划（2026-10-22）

状态：本轮六阶段已执行完成；连接复用已实现，PydanticAI 隔离原型通过，最终回归 104 通过、2 项既有基线缺失失败。基线为 `feat/native-harness` / `41ace3d`。用户已授权先落计划，再执行。

## 目标与范围

先减少现有网关重复建立连接的开销，再以隔离实验判断 PydanticAI 能否减少持久提问和上下文管理的自研工作。保留原有报价授权、预算账本、项目隔离、Worker、停止和未知提交不重发语义。

本轮不直接切换默认 Agent，不重写视频制作流程，不调用真实付费模型或媒体服务。实验不能证明真实模型质量和真实交付提速。用户随后授权更新架构文档并本地提交，本次提交包含实现、测试、实验脚本和文档，不推送远端。

当前产品架构和隔离候选的关系见[架构图](NATIVE-HARNESS.md#当前架构2026-10-22)：连接池已进入共享网关，PydanticAI 未进入产品运行路径。

## 执行顺序及验收

| 阶段 | 工作 | 验收证据 |
|---|---|---|
| 1. 基线 | 读取网关调用方、应用生命周期和测试；建立 HTTP/1.1 本地供应商探针 | 同样 N 次请求的实际 TCP 连接数、耗时、请求计数；隔离数据 |
| 2. 连接复用 | 应用生命周期内复用 HTTPX AsyncClient；单个响应单独关闭；独立脚本继续可调用网关 | N 次成功请求复用连接；项目令牌/凭据不串用；失败、取消和未完成流保留正确账本状态；无自动重试；关闭释放客户端 |
| 3. 候选环境 | 在 `.local/` 建独立 Python 环境，验证 PydanticAI 与当前锁定依赖的解析兼容性 | 记录精确安装版本和冲突；产品 requirements 和运行环境不变 |
| 4. 持久提问原型 | 使用真实 PydanticAI 循环和工具延迟机制；通过现有计费网关访问本地 Responses 替身；待回答调用和历史存隔离文件/数据库 | 初始进程结束后，新进程读取记录、注入答案继续；同一待办不能重复执行；未经用户回答不能执行批准后的操作 |
| 5. 上下文原型 | 完整历史留档，发送前生成受控工作上下文；保留固定用户约束、近期完整工具往返和当前工程事实 | 长历史请求体积下降；工具调用/结果配对完整；关键约束可见；原始记录不丢；明确区分确定性传输验证与模型理解质量 |
| 6. 回归与结论 | 跑新增检查、原有回归及 native/Codex 两种隔离端到端流程；记录阶段结果与候选采用判断 | 新增失败为 0；原有两项缺失历史基线单列；给出复现命令、证据位置、改动范围、未验证项 |

## 实施约束

- 连接复用先验证同等请求的连接数减少；本机延迟只作观察，不承诺公网提速。
- 使用进程生命周期显式管理连接，不把一个 AsyncClient 跨事件循环复用。请求级 Authorization 必须独立设置。
- 候选仅进入实验脚本，不注册成产品第三种运行时；SDK 不得绕过现有计费网关，明确关闭自动模型请求重试。
- 原型的暂停恢复必须用新的进程验证，不能仅在同一对象上继续。持久状态仅在 `.local/`，不写入用户业务数据。
- 上下文裁剪不直接按消息数截断工具链；授权和花费依据仍取数据库，不从模型摘要恢复授权。
- 如果安装依赖冲突，记录精确冲突并在独立环境继续验证；不得为实验升级产品依赖。
- 若候选不能减少实际维护代码或破坏安全边界，保留原生底座，记录结论，不强行迁移。
- 回退只撤销本轮连接复用改动；原型与依赖在隔离目录，可不启用；不得重置或清理用户已有未提交文件。

## 参考与已有证据

- [本项目原版对比报告](NATIVE-HARNESS-COMPARISON-2026-10-22.md)
- [HTTPX 连接池](https://www.python-httpx.org/advanced/clients/)
- [PydanticAI Deferred Tools](https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/)
- [PydanticAI OpenAI-compatible 模型](https://pydantic.dev/docs/ai/models/openai/)
- [Pi 的上下文转换设计](https://github.com/earendil-works/pi/tree/main/packages/agent)
- [LangGraph 中断与副作用幂等](https://docs.langchain.com/oss/python/langgraph/interrupts)

## 执行记录

### 1–2. 连接复用：保留改动

`server/local/gateway.py` 增加应用生命周期连接池，`main.py` 在启动后台任务前创建池，在结束所有 Agent 后关闭。独立脚本或无 lifespan 的测试仍使用请求级客户端。请求结束只关闭该响应；`AsyncExitStack` 负责各条错误/取消路径的资源释放。

认证仍按请求传入；上游 Cookie 不回传到下一请求，避免共享连接顺带共享供应商会话。没有新增依赖，没有自动重试。

探针 `scripts/gateway_pool_probe.py` 使用真实 HTTP/1.1 loopback 服务、真实共享计费网关和独立数据库，每组 11 次请求（含 401/500 和错误后的成功请求），运行 3 组：

| 指标 | 改动前 | 连接池 |
|---|---:|---:|
| 每组实际请求数 | 11 / 11 / 11 | 11 / 11 / 11 |
| 每组 TCP 连接数 | 11 / 11 / 11 | 1 / 1 / 1 |
| 每组总耗时（秒） | 1.8219 / 1.3078 / 1.3225 | 0.2752 / 0.2311 / 0.2304 |
| 总耗时中位数（秒） | 1.3225 | 0.2311 |

连接数减少为确定性结果；耗时包含客户端初始化、网关与数据库处理，不能解释为公网握手耗时或真实模型加速。改动前同一复用检查已明确失败，改动后通过。

新增回归覆盖连接/流式阶段取消后费用保持 `reconciling`、第二请求继续成功且池不关闭、最终关闭释放客户端、池启动失败不启动 Worker。探针还核对逐请求凭据、Cookie 隔离、跨项目令牌拒绝、账本状态及请求数量没有因重试增加。

证据：

- [基线](../.local/gateway-pool-p533g9lx/summary.json)
- [改动前明确失败的复用检查](../.local/gateway-pool-e9z5v4t5/summary.json)
- [连接池结果](../.local/gateway-pool-ox6fyeaj/summary.json)

### 3. 候选依赖：独立环境验证通过

实际安装在 `.local/pydantic-harness-venv/`：PydanticAI Slim **2.59.0**、OpenAI SDK **3.36.1**、Pydantic **2.12.4**。`pip check` 通过。

分别对顶层 `requirements.txt` 和完整 `requirements.lock.txt` 做依赖解析，均未发现约束冲突。完整锁解析允许保留已有版本；若正式接入，本次解析相对产品锁新增 14 个包，包含 `httpx2/httpcore2`、`pydantic-graph`、OpenAI SDK、tiktoken 和遥测 API 包。不能把 slim 理解成无依赖。实验安装的 certifi 为 2026.10.19，完整产品锁解析选择 2026.10.18；两种证据分别保存。

产品 `.venv`、`requirements.txt` 和产品锁均未升级。首次 pip 约束文件含 extras 被拒绝，随后用纯版本约束完成解析；下载期间有一次源站连接超时，重试后成功。

- [安装报告](../.local/pydantic-install-20261022.json)
- [完整产品锁兼容解析](../.local/pydantic-full-lock-compatibility-20261022.json)
- [实际实验环境精确版本](../.local/pydantic-harness-requirements-20261022.lock.txt)

### 4–5. PydanticAI 原型：机制可行，保留为实验

实现于 `scripts/pydantic_harness_probe.py`，复用现有 `parity_web_probe.ModelFixture`。产品后端用原 `.venv` 启动，SDK 用独立环境的子进程执行，所有模型请求经真实私有计费网关；真实业务 `get_project` 通过现有工具网关执行。没有向产品注册 PydanticAI 运行时。

结果：

1. 第一个 SDK 进程发起 `ask_user`，产生 DeferredToolRequests；历史与待回答调用存入隔离 SQLite 后进程退出。此时只发生 1 次模型请求，没有擅自继续。
2. 第二个 SDK 进程读取持久状态，通过 DeferredToolResults 注入测试答案，再调用真实 `get_project` 并完成；总模型请求数为 3。两个进程 PID 不同。
3. 第三个进程重复恢复，SQLite 状态门禁拒绝重复派发，模型请求数仍为 3。`resuming` 状态不会自动重放；此原型没有实现未知恢复结果的运营核对界面。
4. 同一候选分别发送完整与处理后的长历史。使用 ProcessHistory，只将 22 个过时的 `get_project` 结果替换为留档标记，保留最近 2 个结果、固定要求、全部 24 次用户修改，以及全部 24 对工具调用/结果。
5. 请求体从 **297,658 字节降至 35,330 字节，减少 88.13%**；输入原始历史保持不变并单独留档。这个比例来自刻意构造的重复大型快照，不代表真实生产会话的普遍收益。
6. 共 5 次模型请求，计费网关对应 5 条成功用量记录，媒体制作任务为 0；SDK 自动请求重试显式关闭。

这里的 `ask_user` 是候选的延迟工具适配，不是已改造产品的 `AgentTools.question`。暂停状态门禁、用户答案身份校验接入点、历史留档及上下文策略仍需应用负责。第三方库提供协议循环和延迟调用机制，不自动完成产品的审批与恢复。

初次运行发现 2.59.0 的 `run_stream_events` 必须使用异步上下文管理器；按本机安装版本文档修正后通过。实验没有验证模型能否正确理解裁剪后的历史，没有使用模型生成摘要，也没有对任意工具结果做通用截断。

- [原型结果](../.local/parity-web-7q7dsaor/summary.json)
- [实际请求](../.local/parity-web-7q7dsaor/model-requests.json)
- [完整历史留档](../.local/parity-web-7q7dsaor/context-full-archive.json)

### 6. 回归与采用判断

连接池下 native、Codex 两种完整非付费端到端均通过，仍各为 26 次模拟规划请求和 7 次模拟媒体提交。覆盖停止、重启不重复提交、B 重做/A-C 复用、强制重做、字幕修改不新增生成、图片回传及 MP4/剪映 ZIP 交付。

- [native 验收](../.local/parity-web-uk34l55x/summary.json)
- [Codex 回退验收](../.local/parity-web-ymk_wcue/summary.json)
- [最终完整回归 JUnit](../.local/harness-improvement-final-tests-20261022.xml)

最终完整回归为 **104 通过、2 失败**，耗时 20.40 秒。失败仍为已知两项缺失文件：`test_catalog_contracts` 和 `test_baseline_hashes_and_demo_rejected`。没有跳过或伪造历史基线。安全与 native 专项为 **30 通过**；`git diff --check` 通过。端到端通过后补强了连接池初始化顺序，并用最终完整回归中的生命周期检查验证正常退出和启动失败清理。

**采用判断：保留连接复用；保留 PydanticAI 为候选原型，暂不整体迁移。** 本轮证明它能通过现有网关实现跨进程提问恢复和上下文处理，也暴露出持久状态门禁仍需自研、额外依赖增加等成本。尚未将完整 56 工具目录、图片回填、所有停止/审批/错误路径接入候选并运行同等产品验收，也没有真实模型质量证据，因此不能宣称可以删除整个 NativeRunner。

后续若推进正式接入，先在同一真实模型、同一工具目录上验证多轮修改约束保持和暂停恢复，再评估删除多少现有协议/循环代码。native 的生产上下文和提问语义本轮保持原状；不把实验通过描述为已上线能力。

## 复现命令

```powershell
# 已有产品环境：连接复用、安全与生命周期
.venv/Scripts/python.exe scripts/gateway_pool_probe.py --baseline
.venv/Scripts/python.exe scripts/gateway_pool_probe.py
.venv/Scripts/python.exe -m pytest tests/test_security.py tests/test_native_harness.py -q

# 单独安装候选；不改产品虚拟环境
.venv/Scripts/python.exe -m venv .local/pydantic-harness-venv
.local/pydantic-harness-venv/Scripts/python.exe -m pip install -r .local/pydantic-harness-requirements-20261022.lock.txt
.venv/Scripts/python.exe scripts/pydantic_harness_probe.py

# 新克隆没有本机实验锁时，可使用本次候选版本和产品锁约束重新解析
# .local/pydantic-harness-venv/Scripts/python.exe -m pip install "pydantic-ai-slim[openai]==2.59.0" -c requirements.lock.txt

$env:VC_TEST_RUNTIME='native'
.venv/Scripts/python.exe scripts/parity_web_probe.py
$env:VC_TEST_RUNTIME='codex'
.venv/Scripts/python.exe scripts/parity_web_probe.py
Remove-Item Env:VC_TEST_RUNTIME
```

`scripts/verify.ps1` 已加入连接探针，但完整脚本仍会先因两项历史基线缺失而停止；上述探针和端到端已独立执行。`.local` 证据及环境不随 Git 分发。本轮按后续指令本地提交，不推送；没有修改用户配置或产生真实供应商费用。
