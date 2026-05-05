<div align="center">
  <div>
    <img src="./docs/images/switchboard-logo-source.png" alt="SwitchBoard" width="116">
  </div>

  <h1 style="margin-top: 10px;">SwitchBoard</h1>

  <h2>面向 Codex 账号、会话、用量和作图任务的本地控制台。</h2>

  <div align="center">
    <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-green"></a>
    <img alt="Python" src="https://img.shields.io/badge/python-3.13+-blue">
    <img alt="FastAPI" src="https://img.shields.io/badge/backend-FastAPI-009688">
    <img alt="React" src="https://img.shields.io/badge/frontend-React%2019-61dafb">
    <img alt="Docker" src="https://img.shields.io/badge/docker-compose-2496ed">
  </div>

  <p>
    <a href="#最新动态">最新动态</a>
    ◆ <a href="#为什么选择-switchboard">为什么选择 SwitchBoard？</a>
    ◆ <a href="#快速开始">快速开始</a>
    ◆ <a href="#演示">演示</a>
    ◆ <a href="#安装">安装</a>
    ◆ <a href="#文档">文档</a>
  </p>

  <p><a href="./README.md">English</a></p>
</div>

## 最新动态

- **[2026/05]** 将作图页拆分为聚焦的 feature 模块，并迁移到本地 HeroUI 封装组件。
- **[2026/05]** 优化作图队列和任务设置。
- **[2026/05]** 新增分页图片游廊、单图/整任务删除，以及根据游廊视口自适应的页大小。
- **[2026/05]** 使用 `SWITCHBOARD_DATA_DIR` 统一持久化数据目录配置。

## 为什么选择 SwitchBoard？

SwitchBoard 为本地 Codex 用户提供一个受登录保护的仪表盘，把原本分散在 `CODEX_HOME` 里的运行信息集中起来：当前账号、已保存凭据、会话历史、请求日志、Token 用量、成本估算，以及排队中的作图任务。

- **账号控制** - 查看已知 Codex 账号，扫描当前账号额度，在本地重命名或隐藏账号，并通过替换 `CODEX_HOME/auth.json` 切换账号。
- **会话可见性** - 浏览 Codex 会话，按文本搜索，查看精简事件预览，并在需要时打开原始事件详情。
- **用量与成本复盘** - 按账号、模型、缓存用量、Token 类别和预估美元成本聚合请求日志。
- **作图任务工作区** - 提交文生图和参考图任务，在分页游廊中浏览结果，重试任务，下载图片，并删除不需要的结果。
- **本地优先安全边界** - ChatGPT token 不进 SQLite，WebUI 使用应用密码保护，已保存账号凭据写入私有 auth vault。

## 快速开始

本地启用时，建议在两个终端分别启动后端和前端。

```bash
# 1. 启动后端 API
cd backend
APP_PASSWORD=switchboard \
CODEX_HOME="$HOME/.codex" \
SWITCHBOARD_DATA_DIR=./data/dev \
uv run uvicorn main:app --host 127.0.0.1 --port 8080 --reload
```

```bash
# 2. 启动前端开发服务器
cd frontend
npm install
npm run dev
```

打开前端终端里显示的 Vite 地址，通常是 `http://127.0.0.1:5173`，然后使用 `APP_PASSWORD` 的值登录。

> **前置要求**：Python 3.13 与 `uv`、Node.js 与 npm，以及一个本地 Codex home 目录，例如 `~/.codex`。
>
> **需要更接近打包运行的方式？** 可以使用 [Docker Compose](#docker-compose)，也可以构建前端后通过 FastAPI 统一托管，见[本地类生产运行](#本地类生产运行)。

## 演示

### 仪表盘预览

<div align="center">
  <img src="./docs/images/dashbord.png" alt="SwitchBoard dashboard" width="780">
</div>

### 典型工作流

```text
Codex 本地文件
  -> SwitchBoard 扫描账号、会话和用量日志
  -> FastAPI 提供已认证 API 和 React 应用
  -> 浏览器仪表盘展示账号、用量、会话、请求日志和图片
```

你可以在 UI 中完成这些操作：

- 扫描当前 Codex 账号，查看 5 小时额度和周额度剩余情况。
- 切换到已保存账号，同时保留现有 `auth.json` 的 owner 和私有权限。
- 搜索会话，打开事件预览，并在分页历史中跳转。
- 按账号或未归属分组筛选请求日志，复盘 Token 与成本汇总。
- 使用比例、质量、张数和最多 4 张参考图创建作图任务。

## 安装

本节覆盖更完整的安装选项。最快本地启动方式见[快速开始](#快速开始)。

### 环境准备

后端依赖在 `backend/` 中由 `uv` 管理：

```bash
cd backend
uv sync
```

前端依赖在 `frontend/` 中由 npm 管理：

```bash
cd frontend
npm install
```

### 配置

后端从环境变量读取配置。如果后端进程工作目录里存在 `.env` 文件，也会读取它。

| 变量 | 是否必需 | 说明 |
| --- | --- | --- |
| `APP_PASSWORD` | 是 | 登录 SwitchBoard 使用的密码。 |
| `CODEX_HOME` | 否 | Codex home 目录。如果存在 Docker 风格挂载 `/host-codex` 则默认使用它，否则默认 `~/.codex`。启动时该目录必须存在。 |
| `SWITCHBOARD_DATA_DIR` | 否 | SwitchBoard 持久化数据目录。如果存在 `/data` 则默认使用它，否则使用后端工作目录下的 `data`。保存 `switchboard.sqlite`、`auth-vault/` 和 `images/`。 |
| `SWITCHBOARD_STATIC_DIR` | 否 | FastAPI 要托管的已构建前端目录，通常是 `frontend/dist`。 |
| `SWITCHBOARD_COOKIE_SECURE` | 否 | 控制会话 Cookie 的 `Secure` 标记。本地 HTTP 默认 `false`；部署在 HTTPS 后面时设为 `true`。 |
| `CHATGPT_BACKEND_BASE` | 否 | 扫描账号和代理图片调用时使用的 ChatGPT 后端基础地址，默认是 `https://chatgpt.com/backend-api`。 |
| `SWITCHBOARD_IMAGE_MODEL` | 否 | 默认图片模型，默认是 `gpt-image-2`。 |
| `SWITCHBOARD_IMAGE_RESPONSES_MODEL` | 否 | 调用图片生成工具时使用的 Responses API 主模型，默认是 `gpt-5.4-mini`。 |
| `SWITCHBOARD_IMAGE_RESPONSES_PATH` | 否 | 图片 Responses 调用路径或完整 URL，默认是 `/codex/responses`。 |
| `SWITCHBOARD_IMAGE_TIMEOUT_SECONDS` | 否 | 图片生成超时时间，默认是 `300`。 |
| `SWITCHBOARD_IMAGE_MAX_PROMPT_CHARS` | 否 | 后端允许的最大提示词长度，默认是 `4000`。 |
| `SWITCHBOARD_IMAGE_CONCURRENCY` | 否 | 同时运行的单图任务上限，默认是 `2`；设为 `1` 可恢复串行生成。 |
| `SWITCHBOARD_IMAGE_DEBUG` | 否 | 开启图片请求/响应调试日志；默认是 `false`，token 和图片 base64 仍不会写入日志。 |

根目录 `.env.example` 面向 Docker Compose：

```bash
APP_PASSWORD=change-me
CODEX_HOME=~/.codex
DATA_DIR=./backend/data
CHATGPT_BACKEND_BASE=https://chatgpt.com/backend-api
```

> **安全说明**：不要提交 `.env`、SQLite 数据库、本地 Codex 凭据或生成的私有数据。旧路径变量 `SWITCHBOARD_DB`、`SWITCHBOARD_AUTH_VAULT` 和 `SWITCHBOARD_IMAGE_OUTPUT_DIR` 已移除；请统一使用 `SWITCHBOARD_DATA_DIR`。

## 作图

登录后打开“作图”页面。SwitchBoard 会在内存中使用当前 `CODEX_HOME/auth.json` 里的 ChatGPT access token，因此不需要在 SwitchBoard 中配置图片专用密钥，也不会把 token 发送给浏览器。

常用流程：

1. 输入提示词，然后选择比例、质量档位和生成张数。
2. 可选附加最多 4 张 PNG、JPEG 或 WebP 参考图，每张不超过 10 MB。
3. 提交任务。SwitchBoard 会加入队列、轮询进度，并在完成或失败时弹出通知。
4. 在游廊中浏览结果。页码按图片卡片计数，页大小会根据游廊视口自适应。
5. 预览、下载、停止活跃任务、重试失败任务、删除单张输出，或删除整个任务。

补充说明：

- 游廊会展示生成图片，文件保存在 `SWITCHBOARD_DATA_DIR/images/YYYY/MM/DD/{job_id}/`。
- 作图任务元数据保存在 `SWITCHBOARD_DATA_DIR/switchboard.sqlite`；ChatGPT token 不会写入这里。
- 更深入的作图任务、API 和对接细节见 [docs/image-jobs.md](./docs/image-jobs.md)。

## 本地类生产运行

先构建前端：

```bash
cd frontend
npm install
npm run build
```

然后由 FastAPI 同时提供 API 和已构建前端：

```bash
cd ../backend
APP_PASSWORD=switchboard \
CODEX_HOME="$HOME/.codex" \
SWITCHBOARD_DATA_DIR=./data/dev \
SWITCHBOARD_STATIC_DIR="$PWD/../frontend/dist" \
uv run uvicorn main:app --host 127.0.0.1 --port 8080
```

打开 `http://127.0.0.1:8080`，并使用 `APP_PASSWORD` 登录。

## Docker Compose

在仓库根目录创建 `.env`：

```bash
APP_PASSWORD=change-me
CODEX_HOME=/home/you/.codex
DATA_DIR=./backend/data
```

然后运行：

```bash
docker compose up --build
```

除非你设置了不同的 `PORT`，否则打开 `http://127.0.0.1:8080`。

Compose 会把 `.env` 用于变量替换。宿主机 Codex 目录以可读写方式挂载到 `/host-codex`，宿主机 SwitchBoard 数据目录挂载到 `/data`。容器内部固定使用 `CODEX_HOME=/host-codex`、`SWITCHBOARD_DATA_DIR=/data`，并从 `/app/frontend/dist` 托管已构建前端。

容器进程可能以 root 运行，但 SwitchBoard 替换 `CODEX_HOME/auth.json` 时会保留原文件的 owner 和 group。如果 Codex 挂载改成只读，Docker 模式就只能查看账号、会话、用量，以及不需要写入凭据的图片历史。

## 配置导入和导出

使用 Accounts 工具栏里的导入和导出按钮，可以在不同安装之间迁移 SwitchBoard 本地账号展示状态。

导出的 JSON 包含账号 ID、生成的显示名、自定义名称、隐藏状态、用户和套餐标签、过期状态、最近扫描时间、5 小时剩余、周额度剩余以及 reset 时间。它不包含 ChatGPT token、`auth.json`、会话、请求日志、SQLite 用量缓存、图片文件或 `.env` 值。

导入配置文件时会按 `account_id` 合并：文件中的账号会更新本地展示元数据和最新额度快照，未知账号会创建为占位账号，本地存在但文件中缺失的账号保持不变。当前 Codex 账号永远不会被导入为隐藏状态，导入 `current` 标记也不会切换当前 Codex 账号。

## 文档

- [docs/development.md](./docs/development.md) - 开发命令、架构、仓库结构和贡献说明。
- [docs/image-jobs.md](./docs/image-jobs.md) - 作图任务 API 和任务分发方对接细节。

## 安全说明

- SwitchBoard 会从 `CODEX_HOME` 读取 `auth.json` 以及本地 Codex 会话和状态文件。
- ChatGPT token 不会存储在 SwitchBoard 的 SQLite 数据库中。
- 已保存账号凭据会以私有 `auth.json` 文件形式放在 `SWITCHBOARD_DATA_DIR/auth-vault`，默认不放在 `CODEX_HOME` 下。
- 切换账号会重写本地 `CODEX_HOME/auth.json`；需要重启 Codex 才会生效。
- Docker 中切换账号会保留现有 `auth.json` 的 owner/group，并以 `0600` 权限写入。
- 隐藏账号和自定义名称都是 SwitchBoard 本地元数据。
- 配置导出只包含 SwitchBoard 本地账号展示状态，绝不会包含凭据。
- 图片生成只在内存中读取当前 access token；token 永远不会返回给前端。
- 任务分发方 token 加密保存在私有 auth vault 中，前端只能拿到脱敏摘要。
- 图片 debug 日志和已存储的上游元数据不会包含 access token、Authorization header 的真实值、图片 base64 内容、safety identifier 或 prompt cache key。
- 不要提交 `.env`、SQLite 数据库、生成的私有数据或本地 Codex 凭据。
- 用量成本估算使用本地价格表匹配已知模型名；未知模型的成本会保持为 null。

## 许可证

SwitchBoard 使用 **MIT License**。详见 [LICENSE](LICENSE)。

## 致谢

SwitchBoard 为本地运行 Codex、并希望更清晰、更安全、更可审计地管理账号和用量的人而生。
