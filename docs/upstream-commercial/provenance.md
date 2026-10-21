# 来源、许可与分发边界

此清单是工程来源审计，不是法律免责或权属意见。既有实现接触事实、测试中运行旧基线的事实均保留。上游的版权与许可没有被删除或改名掩盖；原始文件留在只读交接树，哈希清单作为证据。

## 被隔离的旧内容

| 内容 | 来源 / 许可证据 | 决定 |
|---|---|---|
| `@hypit/hypit` 0.2.17 源码、构建产物、TGZ | 精确基线内 LICENSE 是增加商业再分发/多租户限制的 Apache 2.0 修改版；文件字节及 TGZ 内容名单已记录 | 不进入核心源码包、不加载、不转发 CLI。不能归类为标准 Apache-2.0 |
| videocopyer 0.5.0-beta.2 整个发布树 | 根 LICENSE 同样包含额外条件；发布树及 296 个包元数据逐一记录 | 整体不迁入商业包；只在独立黑盒对照进程使用 |
| baseline extensions 排行榜、Last War、Seedance/Seedream | 多项 package 元数据未声明许可，且依赖 author-kit/composition/temporal | 隔离到阶段三，不能因 package.json 无 license 就视作自有 |
| 上游 skills、docs/upstream、提示词和示例 | 随原包交付，未获得独立再分发许可证明 | 只记录路径、分类和哈希；新产品说明重新撰写，原文不进入核心包 |
| 原 D 组件库与 `hypit_reference` 标识 | D 仓库来源不等于独立实现证据 | 不进入核心运行闭包；来源确认后才能复用 |
| 原 D 浏览器/字幕适配器、media processors | 原代码明确依赖 Hypit CLI 或 browser-capture | 核心采用全新采集/文字实现；旧文件仅保留迁移参考 |
| 字体、模型权重、外部引擎 | 基线内文件逐项枚举；未随包的模型/字体不能由文档提及推定许可 | 不随核心包分发；实际素材/字体必须填写来源、许可与 SHA-256 |
| 旧 FFmpeg 8.0.1 essentials | 本机旧测试环境，`--enable-gpl --enable-version3` | 仅运行原基线黑盒比较，未用于新核心验收，未分发 |

清单：`baseline-files.csv` 覆盖文件类型及逐文件 SHA-256；`upstream-dependencies.json` 覆盖直接、可选、peer 依赖及许可证元数据；`upstream-archives.json` 列出 TGZ 所有成员；`legacy-d-files.csv` 覆盖原 D 源码、资源和实验包；`call-sites.json` 覆盖直接和间接引用位置。缺失许可证、外部配置中的依赖或外部模型权重仍标为待核，不伪造完整授权结论。

## 阶段二采用的依赖

| 依赖 | 实际使用与来源 | 许可处理及限制 |
|---|---|---|
| Python 3.12 | 独立 `.commercial-env`，无旧应用 SQLAlchemy 或 Hypit 环境 | 外部解释器，不随源码包分发 |
| FastAPI 0.121.3 / Pydantic 2.12.4 / Uvicorn 0.38.0 | PyPI 安装；其递归实际依赖和许可证文件哈希见 `python-dependencies.json`、`core-python-files.json` | 逐包保留 MIT/BSD 等声明；生产依赖精确锁在 `requirements.lock.txt` |
| Pillow 12.1.1 | PyPI wheel；独立帧合成、字体栅格化 | HPND/Pillow 声明及 wheel 内第三方通知保留；未把“Pillow 许可”当成所有底层库唯一许可 |
| fontTools 4.61.1 | PyPI wheel；读取字体 cmap，测试中做受限 Latin 字体 | MIT；实际字体另行核验 |
| FFmpeg `n9.0.2-28-g669f5ab083-20261015` | BtbN `lgpl-shared` Win64 构建，包 SHA-256 `624803200fd8223faa668691d0cc9d37be3e460d344e4b26948a09d63151e868`，与 GitHub 资产 digest 一致 | 实际包 LICENSE 为 LGPLv3；配置无 enable-gpl/nonfree，EXE 与 DLL 全部哈希锁定；不随源码包分发 |
| OpenH264 | 上述构建的 libopenh264 编码器，用于可在浏览器播放的 MP4 | 源码 BSD-2-Clause 不等于自动享有 Cisco 二进制专利安排；发行编码器来源和相关义务需要单独核验 |
| Playwright 1.62.1 | 运行环境现有官方 npm 包，通过显式模块路径解析 | Apache-2.0；Node、浏览器与模块版本分别记录，不从 Hypit 解析依赖 |
| Chrome for Testing 151.0.7922.34 | Playwright 安装对应 Chromium revision 1234；全新临时上下文 | 记录 ABOUT/terms 和第三方 credits 边界；测试下载不进入源码包。不能把 Chrome 分发简单标为单一 BSD |
| Noto Sans SC | Google Fonts 官方 OFL 目录，字体 SHA-256 `a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da` | OFL-1.1 与 LICENSE 哈希一并保留；只在测试环境，未捆绑到产品 |
| React / React DOM / Scheduler | 前端实际构建依赖，版本和许可证 SHA 见 `frontend-runtime.json` | MIT 通知进入插件 `THIRD-PARTY-NOTICES.md`；未复制原 node_modules |

FFmpeg 许可证取决于具体构建选项，不能仅凭项目名称判断。见 [FFmpeg 官方说明](https://www.ffmpeg.org/legal.html)、[BtbN 构建项目](https://github.com/BtbN/FFmpeg-Builds)。OpenH264 的源码与官方二进制安排不同，见 [源码 LICENSE](https://github.com/cisco/openh264/blob/master/LICENSE) 和 [官方 FAQ](https://www.openh264.org/faq.html)。这些说明支持依赖处理记录，不构成当前产品已获全部商业许可的结论。

## 发行保护

`build_d_core.py` 只复制列明的 17 个 D 核心源码文件及前端结果，不使用原 `vendor_d_baseline.py`。遇到 upstream runtime、vendor、node_modules、TGZ、模型、字体、EXE/DLL 等混入会失败。旧源码和审计证据不随该插件目录发出。插件清单标为开发版，`build-manifest.json` 明确 `redistribution_clearance:false`。

本轮没有创建商业发行 ZIP、安装用户插件或写市场配置。后续发行需要冻结发行平台、许可证通知、相应源码/构建材料、字体/素材/模型授权和编码器义务；不能通过换语言、进程包装或使用外部目录规避任何实际适用的许可条件。
