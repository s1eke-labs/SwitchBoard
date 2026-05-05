# 开发与架构

本文档收纳 README 中移出的开发协作内容。日常启用 SwitchBoard 请看 README；需要改代码、跑检查或理解模块边界时再看这里。

## 开发命令

在 `backend/` 目录运行后端命令：

```bash
uv run pylint --rcfile=.pylintrc .
uv run pytest
APP_PASSWORD=switchboard CODEX_HOME="$HOME/.codex" SWITCHBOARD_DATA_DIR=./data/dev uv run uvicorn main:app --host 127.0.0.1 --port 8080 --reload
```

在 `frontend/` 目录运行前端命令：

```bash
npm install
npm run dev
npm run lint
npm run build
npm run preview
```

`uv run pylint --rcfile=.pylintrc .` 会运行后端 lint 检查。`uv run pytest` 会运行后端测试。`npm run lint` 会运行前端 ESLint 和 TypeScript 检查。`npm run build` 会生成 `frontend/dist`。

## 架构

### 系统概览

```text
┌─────────────────────────────────────────────────────────────┐
│ 浏览器                                                      │
│ React 19 + Vite + Tailwind CSS + HeroUI 本地封装组件         │
└─────────────────────────────┬───────────────────────────────┘
                              │ 已认证 /api 请求
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ FastAPI 后端                                                 │
│ 登录 Cookie、账号 API、会话 API、用量 API、图片 API           │
└───────────────┬───────────────────────┬─────────────────────┘
                │                       │
                ▼                       ▼
┌────────────────────────────┐  ┌─────────────────────────────┐
│ CODEX_HOME                 │  │ SWITCHBOARD_DATA_DIR         │
│ auth.json、sessions、logs  │  │ SQLite、auth-vault、images   │
└────────────────────────────┘  └─────────────────────────────┘
                │                       │
                └──────────────┬────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ ChatGPT 后端                                                 │
│ 账号扫描与 OpenAI Images 兼容的生成代理                      │
└─────────────────────────────────────────────────────────────┘
```

### 关键设计决策

- **扁平 FastAPI 模块**：后端按领域模块组织在 `backend/` 下，不引入很深的框架目录层级。
- **本地元数据边界**：SwitchBoard 元数据写入 SQLite；ChatGPT token 留在 `auth.json` 文件中，永不写入数据库。
- **基于租约的作图 Worker**：图片任务写入 SQLite，并通过数据库租约抢占，主动/被动 Worker 可以共享同一个任务池且不重复执行。
- **HeroUI 支撑的前端基础组件**：React 应用优先使用 HeroUI 的本地封装，SwitchBoard 业务组合放在页面和 feature 模块中。

## 仓库结构

```text
backend/
  main.py             FastAPI 应用和 API 路由
  accounts.py         Codex 账号扫描与切换
  images/             图片提交、任务池、Worker、分发方适配器、存储和 API 代理
  sessions.py         Codex 会话读取和事件预览
  usage.py            用量聚合和请求日志
  db.py               SQLite 初始化和辅助函数
  security.py         登录 Cookie 辅助函数
  tests/              后端测试

frontend/
  src/app/            应用外壳和路由
  src/pages/          仪表盘、会话、请求日志、登录和作图页面
  src/features/       账号、会话、用量和作图 UI 模块
  src/components/     共享 UI 组件和 HeroUI 封装
  src/lib/            API 客户端、错误和工具函数
  dist/               已构建前端输出

docs/images/          Logo 源图和仪表盘截图
```

## 贡献

欢迎贡献。请保持改动聚焦，并守住本地优先的凭据边界。

```bash
# 后端检查
cd backend
uv run pylint --rcfile=.pylintrc .
uv run pytest

# 前端检查
cd ../frontend
npm run lint
npm run build
```

提交信息使用 Conventional Commits：`<type>(<scope>): <summary>`。本仓库偏好中文 summary，除非周边改动本身已经是纯英文。
