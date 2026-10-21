# D 插件：源码拉取与插件包下载说明

更新日期：2026-10-16。适用版本：**D 2.0.0-beta.1 / Windows x64**。

## 1. 仓库、分支与版本

| 项目 | 地址或标识 |
|---|---|
| GitHub 仓库 | [Zefe96/Video-copyer](https://github.com/Zefe96/Video-copyer) |
| 第五阶段分支 | `codex/d-commercial-stage5-beta1` |
| 第五阶段交付提交 | `a02603ee5828b5e954be1d16e13e828bd2e9a3d1` |
| 当前独立项目目录 | `commercial-d/` |
| 交付文件目录 | `commercial-d/artifacts/distribution/` |

目前第五阶段代码位于上述分支，**尚未合并到 main**。进入仓库后应切换到指定分支。后续说明文档可能继续更新；本文的固定下载链接指向交付提交，不会随分支移动而改变文件内容。

## 2. 我应该下载哪一份？

| 目的 | 推荐方式 | 包含内容 |
|---|---|---|
| 使用 D 插件 | 下载 `workbench-d-2.0.0-beta.1-windows-x64.zip` | 插件入口、MCP、Agent 技能、已构建工作台、安装配置脚本和说明 |
| 继续开发、提交修改 | 用 Git 拉取指定分支 | 项目源码、测试、验收记录、交接文档及交付包，可跟踪后续更新 |
| 无需 Git 的源码交接 | 下载 `workbench-d-2.0.0-beta.1-source-handoff.zip` | 第五阶段独立源码快照、构建脚本、测试和开发交接文档；不含 Git 历史 |

插件 ZIP 不包含 Python、FFmpeg、模型权重、字体及账户密钥。它是需要配置运行环境的插件目录包，不是双击即完成安装的 EXE。

## 3. 首次拉取源码

先安装 Git，然后在准备存放项目的父目录打开 PowerShell：

```powershell
git clone --branch codex/d-commercial-stage5-beta1 --single-branch https://github.com/Zefe96/Video-copyer.git Video-copyer-D
Set-Location .\Video-copyer-D
git branch --show-current
git log -1 --oneline
Set-Location .\commercial-d
```

`git branch --show-current` 应输出 `codex/d-commercial-stage5-beta1`。最后进入的 `commercial-d` 才是本次独立版本的开发根目录。

**注意目录区别：**仓库外层还保留历史代码；当前插件入口是 `commercial-d/plugins/workbench-d`，不要把外层同名目录当作本版本使用。

### 已经有仓库时

在已有仓库根目录先检查本地修改：

```powershell
git status
git fetch origin
```

若有未提交修改，先自行提交或备份；也可按上面的首次拉取步骤创建一个新目录。不要直接执行 `git reset --hard` 或清理文件。

本地还没有目标分支时：

```powershell
git switch --track origin/codex/d-commercial-stage5-beta1
```

本地已有目标分支时：

```powershell
git switch codex/d-commercial-stage5-beta1
git pull --ff-only origin codex/d-commercial-stage5-beta1
```

若 `--ff-only` 提示分支分叉，应先检查本地提交并处理合并，不要强制覆盖。

### 精确复现第五阶段交付版本

日常开发使用分支最新版本。若需检查原交付快照，可在仓库中另建一个工作目录：

```powershell
git worktree add --detach ..\D-stage5-snapshot a02603ee5828b5e954be1d16e13e828bd2e9a3d1
```

该目录处于 detached HEAD，适合复现检查；若要在那里开发，先创建自己的分支。

## 4. 通过浏览器下载插件包

打开 [GitHub 交付文件目录](https://github.com/Zefe96/Video-copyer/tree/codex/d-commercial-stage5-beta1/commercial-d/artifacts/distribution)，选择需要的 ZIP，再点击文件页的 **Download raw file** 下载按钮。

固定版本入口：

- [下载插件 ZIP](https://github.com/Zefe96/Video-copyer/raw/a02603ee5828b5e954be1d16e13e828bd2e9a3d1/commercial-d/artifacts/distribution/workbench-d-2.0.0-beta.1-windows-x64.zip)
- [下载源码交接 ZIP](https://github.com/Zefe96/Video-copyer/raw/a02603ee5828b5e954be1d16e13e828bd2e9a3d1/commercial-d/artifacts/distribution/workbench-d-2.0.0-beta.1-source-handoff.zip)
- [查看 SHA256SUMS.txt](https://github.com/Zefe96/Video-copyer/blob/a02603ee5828b5e954be1d16e13e828bd2e9a3d1/commercial-d/artifacts/distribution/SHA256SUMS.txt)

仓库若需要访问权限，先登录有权限的 GitHub 账号。出现 404 也可能是未登录或无权限；可以使用已认证的 Git 拉取后，从本地交付目录取包。不要将 GitHub 令牌写进下载链接、脚本或文档。

GitHub 的 **Code → Download ZIP** 下载的是所选分支的整个仓库快照，与上述单独的插件 ZIP 不同。

## 5. 使用 PowerShell 下载并校验

以下命令适用于无需额外登录即可读取仓库文件的环境。需要认证时优先使用浏览器登录下载或已认证的 Git 拉取。

在准备存放下载文件的目录运行：

```powershell
$downloadDir = Join-Path (Get-Location) 'D-2.0.0-beta.1-download'
New-Item -ItemType Directory -Path $downloadDir -Force | Out-Null
$releaseBase = 'https://raw.githubusercontent.com/Zefe96/Video-copyer/a02603ee5828b5e954be1d16e13e828bd2e9a3d1/commercial-d/artifacts/distribution'
$pluginZip = Join-Path $downloadDir 'workbench-d-2.0.0-beta.1-windows-x64.zip'

if (Test-Path -LiteralPath $pluginZip) { throw '目标 ZIP 已存在，请使用新目录或先检查现有文件。' }
Invoke-WebRequest -Uri "$releaseBase/workbench-d-2.0.0-beta.1-windows-x64.zip" -OutFile $pluginZip

$expectedHash = '954250a46c402e35c76cb3f8dc3ac7144801a55edf45b3cf7e925f98023141d4'
$actualHash = (Get-FileHash -LiteralPath $pluginZip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $expectedHash) { throw '插件包 SHA-256 不匹配，请重新下载并确认版本。' }
'插件包校验通过'
```

浏览器下载的文件也可以单独校验：

```powershell
Get-FileHash -LiteralPath '.\workbench-d-2.0.0-beta.1-windows-x64.zip' -Algorithm SHA256
Get-FileHash -LiteralPath '.\workbench-d-2.0.0-beta.1-source-handoff.zip' -Algorithm SHA256
```

对应的固定 SHA-256 如下，比较时忽略字母大小写：

**插件 ZIP：**

```text
954250a46c402e35c76cb3f8dc3ac7144801a55edf45b3cf7e925f98023141d4
```

**源码交接 ZIP：**

```text
75d5c0db1525b398f7e5ec2045c8d2eb38c4050ab40bd61001efc6f2893435fa
```

这些哈希对应上述交付提交。将来下载其他版本时，应读取该版本自己的 SHA256SUMS.txt。

## 6. 解压后怎么使用

在 ZIP 所在目录执行，目标目录应为新目录：

```powershell
if (Test-Path -LiteralPath '.\D-plugin-beta1') { throw '解压目标已存在，请另选新目录。' }
Expand-Archive -LiteralPath '.\workbench-d-2.0.0-beta.1-windows-x64.zip' -DestinationPath '.\D-plugin-beta1'
Set-Location .\D-plugin-beta1\workbench-d
```

解压后应能看到：

```text
workbench-d/
  .codex-plugin/plugin.json
  .mcp.json
  README.md
  scripts/setup.py
  scripts/run.ps1
  skills/workbench-d/SKILL.md
  runtime/api/
  dist/
  docs/
```

接下来打开包内 `README.md`：

1. 准备 Python 3.12 和符合本项目要求的 FFmpeg/FFprobe。
2. 用 `scripts/setup.py` 创建或关联独立运行环境。
3. 用 `scripts/run.ps1 -Mode doctor` 检查依赖。
4. 按 README 的 Codex 接入步骤注册个人插件市场并安装，重新打开任务加载插件。

完整在线说明：[插件安装与运行 README](https://github.com/Zefe96/Video-copyer/blob/codex/d-commercial-stage5-beta1/commercial-d/plugins/workbench-d/README.md)。本次上传包已验证本地 MCP/HTTP 运行；Codex 个人市场安装与 UI 发现尚未完成实机验收。

## 7. 交给后续 Agent 开发

源码拉取后，先让 Agent 阅读：

1. `commercial-d/AGENTS.md`
2. [Agent 交接指南](https://github.com/Zefe96/Video-copyer/blob/codex/d-commercial-stage5-beta1/commercial-d/docs/commercial/AGENT-HANDOFF.md)
3. [20 项详细待开发说明](https://github.com/Zefe96/Video-copyer/blob/codex/d-commercial-stage5-beta1/commercial-d/docs/commercial/DEVELOPMENT-BACKLOG.md)
4. `commercial-d/docs/commercial/total-matrix.md`
5. `commercial-d/docs/commercial/evidence/stage5-verification.json`

可直接交给 Agent 的任务说明：

> 请在 commercial-d 目录接续开发 D 2.0.0-beta.1。先读取 AGENTS.md、Agent 交接指南、待开发项和总验收矩阵，确认本次指定的 D5 任务编号后实施。修改源目录，使用本项目构建脚本生成插件；保留已经通过的测试与明确的能力边界，每项完成后补充验收证据。

当前版本有 68 项回归测试通过、41 个 MCP 工具及本地工作台闭环验证。模型质量、完整 3D、剪映实机兼容和最终商业分发审核仍在待开发清单中；下载或安装成功不表示这些能力已经完成。
