# 阶段验收记录

日期：2026-10-16。独立审查已接受阶段一盘点及阶段二 R1/R2 的限定修复范围，阶段三 PARTIAL。第四阶段已实施并提供本地证据，尚未独立验收。当前结果以 [stage4.md](stage4.md)、[总矩阵](total-matrix.md) 及最新 XML/JSON 为准。下文 35 项等数字为第三阶段历史记录，不能当作当前测试数量。

## 实际结果

| 验证 | 结果 | 证据 |
|---|---|---|
| 基线身份 | ZIP SHA-256 与要求一致；对照前逐个核验原包 12,373 文件 | `baseline-zip.json`、两个 comparison JSON |
| 来源盘点 | 12,374 实际文件、296 包、1 TGZ、329 调用引用、43 命令 | `inventory-summary.json`、CSV/JSON 清单 |
| 核心与新增测试 | 35 通过，0 失败、0 跳过 | `core-tests.xml` |
| 干净环境 | 新 Python venv；没有旧应用 SQLAlchemy、没有可解析的 Hypit 模块；插件只含白名单核心代码 | `clean-package.json`、`python-dependencies.json` |
| 真实 MCP 分发入口 | 创建、编辑、校验、渲染、宿主重启、命令去重、取消、交付全部完成 | `clean-package.json` |
| 真正杀进程恢复 | 杀死私有测试数据库记录的工作进程，等待真实租约到期，重新执行成功 | `test_real_worker_crash_restart` |
| 失败、取消与重试 | 排队取消、运行中取消、捕获超时、错误持久化、显式重试、旧 lease 无法提交 | 对应核心测试 |
| 旧 D 工程接入 | 只读打开旧库，导入明确修订及素材，实际渲染，源库 SHA 不变 | `test_transfer_legacy_workspace_readonly` |
| 多轨、裁切、动画、透明度 | PNG 像素精确检查；alpha MOV 确认 RGBA，透明背景保留 | `test_layer_crop_alpha_keyframes_and_crossfade` |
| 分数帧率及音轨 | 30000/1001 fps，正确视频裁切、延迟、音量、时长 | `test_rational_clock_audio_and_video_trim` |
| 中文文字 | 字体 cmap 回退、词级高亮、描边、阴影；缺字、溢出会失败 | `test_caption_chinese_fallback_highlight_missing_overflow` |
| 浏览器采集 | 独立上下文，实际点击改变指定帧、任务依赖，下一上下文不继承 cookie | `test_browser_capture_dependency_order_and_login_isolation` |
| 真实前端 | 创建→添加图层→保存修订→预览→渲染→交付下载，440px 无横向溢出 | `ui.json`；`artifacts/d-commercial/ui/` 截图 |
| TypeScript / Vite | 类型检查及 D 单独生产构建成功 | 实际执行命令见下文 |
| 插件结构 | `plugin-creator` 验证器通过 | `plugins/workbench-d/.codex-plugin/plugin.json` |

核心测试只覆盖本次新内核及桥接；没有把上一任务的 406 项旧后端通过数字当成本次回归结果。测试报告的一条 AnyIO/Starlette 弃用警告不影响结果，未隐藏。

## 原阶段二同素材效果对照（历史证据，不构成 R1/R2 验收）

原基线与新核心运行在不同进程，原运行时不加入新核心的依赖路径。所有基线提交前核对 quote 的全部请求为 local，模型请求为 0。原基线需要 libx264，因此黑盒一侧使用原测试环境的 GPL FFmpeg；新核心一侧使用独立 LGPL/OpenH264 构建，两者身份分别记录。

1. **动态素材、多轨与音轨**：同一 2 秒 320×180/24 fps 动态素材，两层不同大小视频及中文标题，音轨相同且 gain=0.5。双方均输出 48 帧、2 秒。5 个采样帧的画面/布局 RGB 平均绝对误差为 2.495–3.136 / 255，低于事先在脚本中明确的 12/255 阈值。音频统一为 48kHz 单声道后均为 96,000 样本，零偏移相关度 0.9993657405。第一次相关性检查发现基线是双声道、核心是单声道，已修正对比的声道归一化；未修改结果来伪造一致性。
2. **原生中文标题**：相同 Noto Sans SC 字体文件、文字、字号、边界和中心对齐，黑底独立渲染。双方均为 48 帧。基线字形框 `(90,4,232,26)`，新核心 `(91,0,231,23)`，最大边界差 4 px，落在 6 px 的明确容差内。它们由不同文字栅格器产生，不宣称字节一致。
3. **透明与词级时间**：新核心通过 alpha 像素、帧域高亮及换行/回退测试；上述黑盒基线对照不覆盖全部 Fine Caption 动画或每一种转场，也没有把先前 3 秒彩条案例当成全面质量证据。

结果：`evidence/baseline-comparison.json`、`evidence/baseline-text-comparison.json`。可视接触表：`artifacts/d-commercial/comparison/compare-024.png`、`artifacts/d-commercial/comparison-text/compare-024.png`（左为基线，右为新核心）。MP4、WAV、PNG 序列、原生输入文件与引用素材均在各自对照目录内，便于复核。

## 复现

环境：Windows x64、Python 3.12；所有路径以仓库根为工作目录。外部工具、字体和浏览器不打包；准确版本/哈希见 `provenance.md` 及 evidence。下载准备脚本在首次执行时联网，不应在离线验收中重复下载。下载 URL 可能随 latest/main 变化，复现须使用已记录的哈希/归档字节，不能把当前 latest 自动当成同一构建。

```powershell
# 新建独立环境后安装锁定生产依赖及独立测试依赖
.commercial-env/Scripts/python.exe -m pip install -r plugins/workbench-d/requirements.lock.txt
.commercial-env/Scripts/python.exe -m pip install pytest==8.4.2 httpx==0.28.1 jsonschema==4.25.1
./scripts/test_d_core.ps1 -Python "$PWD/.commercial-env/Scripts/python.exe"

# 前端：在 apps/web 中执行
node node_modules/typescript/bin/tsc -p tsconfig.app.json --noEmit
node node_modules/vite/bin/vite.js build --config vite.workbench-d-plugin.config.mjs --configLoader runner

# 回到根目录，使用明确 allowlist 生成开发源码插件
.commercial-env/Scripts/python.exe scripts/build_d_core.py
# 配置 D_FFMPEG/D_FFPROBE 后，PYTHONPATH 为空运行真实分发入口测试
.commercial-env/Scripts/python.exe scripts/verify_d_core_clean.py
```

网页实际测试：启动 `plugins/workbench-d/runtime/api/launcher.py http`，设置 `WORKBENCH_D_PORT=19449`、`D_CORE_DATA` 指向独立测试数据目录；配置 `D_PLAYWRIGHT_MODULE`、`PLAYWRIGHT_BROWSERS_PATH` 后执行 `node scripts/verify_d_core_ui.mjs <仓库根路径>`。

黑盒对照：配置 `PYTHONPATH=services/api`、`D_FFMPEG`、`D_FFPROBE`、`D_TEST_FONT` 后执行 `scripts/compare_d_core_baseline.py`，以及 `--text-only`。`--analyze-existing` 可只重新测量已留存的同一成片，不再调用原基线。原基线 tsx 需要 Windows 用户信息；沙箱中会出现 `uv_os_get_passwd` 错误，实际对照在获准的独立进程中完成，原源树不改动。

## 仍有的依赖与功能缺口

- 当前自有工程语义、核心渲染与采集真实可用；原 SVML、完整分组画布/可见回执、任意旧复杂 D 合同的自动转换不是已完成项。桥接遇到无法保持语义的字段直接报错。
- 阶段三的当前实现及剩余缺口以 [stage3.md](stage3.md) 为准；旧“全部留在阶段三”描述已过期。完整流程复用仍延后；审片反馈、剪映兼容与导出安装闭环留在阶段四。旧源码中相关 Hypit 引用仍在审计范围内，但未进入新核心分发目录。
- 页面交互只有明确 URL/来源/selector 的独立上下文；未提供用户登录态导入、复杂实时站点、WebRTC、弹窗多页录制的保证。
- 中文及 Latin 的帧域排版已测；完整文字塑形、所有 Emoji 和全部旧字幕 recipe/转场库尚未逐项对照。4 px 字形框差异保留为可见事实。
- 没有高并发、多租户、4K 长片性能或所有机器编解码矩阵承诺。单节点内部中断可能重做，完成节点通过哈希复用。
- 编码器专利、Chrome 二进制条款、所有外部模型/素材权属以及最终发行时的源码/通知义务仍须按准确分发方式审核。没有创建完整商业发行包或宣称法律洁净室。
