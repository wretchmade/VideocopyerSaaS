# Native harness 与原版 Codex 对比实测（2026-10-22）

本文保留连接池改动前的原始对照数据。后续已落地共享规划网关连接池，完整回归更新为 104 通过、2 项既有基线缺失失败，两种底座端到端再次通过；详见[改进执行记录](NATIVE-HARNESS-IMPROVEMENT-PLAN-2026-10-22.md)与[当前架构图](NATIVE-HARNESS.md)。PydanticAI 仍为隔离候选，未替换 NativeRunner。下文“未修改源码、未提交”描述的是对照实验当时的操作。

结论：本次覆盖的非付费功能链路未发现新增回归；native 减少了本地规划循环耗时和请求体积。真实模型规划质量、真实费用和完整视频交付性能仍未验证，不能据此宣布满足历史双性能门槛。

## 对照与隔离

- 原版：`main`，`cd76166e5e26ebc130a3428aa881db90904282fc`。通过 `git archive` 导出到 `.local/harness-baseline-main-20261022/`，使用原版源码、原版编译的前端和原版测试。
- 候选：`feat/native-harness`，`41ace3dbe0e8633e7f2cbdaaa5992eb2b8a223b6`，`VC_TEST_RUNTIME=native`。
- 回退：相同候选分支，`VC_TEST_RUNTIME=codex`。
- Codex 固定 0.163.0，共用已安装依赖及 FFmpeg/字体；模型名均为 `doubao-seed-2-1-pro-260915`，实际模型和媒体供应商均为 loopback 夹具。真实供应商调用为 0。
- 每轮独立数据库、项目和工作目录。未切换当前分支、未修改产品源码、未修改用户配置，未提交 Git。

## 回归结果

| 验证 | main 原版 | feat/native-harness |
|---|---:|---:|
| Python 回归 | 85 通过 / 2 失败 | 101 通过 / 2 失败 |
| native 专项 | 不适用 | 16 项全部通过 |
| TypeScript / Vite 构建 | 通过 | 通过 |
| 画布图回归 | 本轮未单独跑 | 通过 |
| 隔离浏览器、API、FFmpeg 端到端 | 通过 | native 和 Codex 模式均通过 |

两边失败完全一致，均为 `FileNotFoundError`：

1. `test_catalog_contracts` 缺少 `docs/evidence/parity/installed-tools.json`。
2. `test_baseline_hashes_and_demo_rejected` 缺少 `docs/evidence/template-baseline-20261020/` 的冻结文件。

没有跳过失败测试或用当前实现伪造历史基线。native 专项包含完整工具结果/图片、不能由模型授权制作、提问/停止、重启只读核对、HTTP/断流/不完整或重复调用、上下文及轮次上限、费用未知保留预留、停止等待工具回执、项目隔离和会话切换。

## 相同端到端场景

三种配置均通过：工程创建与报价、浏览器报价弹窗与节点选择、SSE 游标、Worker 重启不重复提交、全局停止、只改 B 复用 A/C、完成后修改 B/C、提示词不变强制重做 B、字幕修改无新增生成、图像审片回传、后台终态回流、MP4 与剪映 ZIP 配套交付、旧交付仍可下载。

每轮均为 26 次模拟规划请求、7 次模拟媒体提交，工具目录均为 56 项。MP4 与 ZIP 实际生成且非空。剪映客户端打开、编辑、保存和重开未在本次测试范围内。

## 探索性测量

| 指标 | main 原版 Codex | native | 分支内 Codex 回退 |
|---|---:|---:|---:|
| 首轮脚本规划完成（秒） | 2.847 | 1.475 | 3.021 |
| 停止 API 接受（秒） | 0.011 | 0.012 | 0.012 |
| 两次配套导出 HTTP 耗时（秒） | [0.442, 0.909] | [0.5, 0.935] | [0.61, 0.901] |
| 首请求 JSON UTF-8 字节数 | 74,757 | 58,467 | 74,639 |
| 全场景请求累计字节数 | 2,963,187 | 2,494,661 | 2,953,150 |

native 相对严格原版样本的脚本规划耗时少 1.372 秒（48.2%）；首请求体积减少 21.8%。这是 JSON 字节数，不是 token 或账单。

native 规划完成时采样到 0 个 Codex/MCP 子进程；分支 Codex 样本采到 1 个 codex.exe 和 2 个 MCP Python 进程条目，含启动器/子进程，不能当作 3 个独立 Agent。没有测量峰值内存或并发容量。

每个主配置只有 1 次完整主样本；轮询粒度约 0.2 秒，不报告 p95 或稳定性能承诺。分支 Codex 的启动阶段与原版前端编译有短时重叠，因此其耗时仅作辅助观察。原版另有一轮“原版后端 + 分支前端”的兼容性探索通过，首轮 3.041 秒，保存在 `.local/harness-baseline-main-20261022/.local/parity-web-1trxxwpd/`，未混入严格原版主表。

## 未证明的部分

- 夹具预定模型输出与工具轨迹，不能证明真实火山方舟协议兼容性、自由规划质量或成功率。
- native 当前没有自动历史压缩；遇到上下文上限会停止，失败/中断后的新消息会以项目快照建立新会话。长会话约束保持需另做真实场景测试。
- 导出 HTTP 耗时不是需求到交付的 `T_delivery`；也未测试真实媒体排队与生成。
- 历史门槛要求规划至少减少 30% 且 3 秒、交付至少减少 20% 且 15 秒，并满足质量和费用护栏。本次本地规划样本只省 1.372 秒，真实交付、质量、费用及统计区间均无证据，不能宣布达标。

## 复现与证据

分支中执行 `npm run build`、`npm run test:workflow`；Python 通过 `.venv/Scripts/python.exe -m pytest` 运行 `scripts/verify.ps1` 列出的 9 个测试文件。端到端：

```powershell
$env:PYTHONUTF8='1'
$env:VC_TEST_RUNTIME='native'
.venv/Scripts/python.exe scripts/parity_web_probe.py
$env:VC_TEST_RUNTIME='codex'
.venv/Scripts/python.exe scripts/parity_web_probe.py
Remove-Item Env:VC_TEST_RUNTIME
```

- 机器可读汇总：[harness-comparison-20261022.json](../.local/harness-comparison-20261022.json)。
- 分支回归：[JUnit](../.local/harness-compare-tests-20261022.xml)。
- 原版回归：[JUnit](../.local/harness-baseline-main-20261022/.local/baseline-tests.xml)。
- native：[summary.json](../.local/parity-web-hei8qzep/summary.json)。
- 分支 Codex：[summary.json](../.local/parity-web-u5il81aq/summary.json)。
- 严格原版：[web-protocol.json](../.local/harness-baseline-main-20261022/docs/evidence/parity/web-protocol.json)，原始请求、数据库和日志在 `.local/harness-baseline-main-20261022/.local/parity-web-2wr9k4rz/`。

以上 `.local` 证据只保留在本机，不随 Git 分发。
