# 日记管理平台

> AI 驱动型个人日记与自我认知平台

通过日记数据建立深度自我理解，获得个性化人生指导。

## 技术栈

| 层面 | 技术 |
|---|---|
| 前端 | Nuxt.js 3（Vue 3 + TypeScript）+ TailwindCSS + Pinia |
| 后端 | Python + FastAPI + SQLAlchemy |
| 数据库 | PostgreSQL 15 |
| AI 模型 | DeepSeek API |
| 部署 | Docker Compose |

## 项目结构

```
diary-platform/
├── docker/                     # Docker 构建、编排与部署文件
├── backend/                    # 后端服务
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 配置管理
│   ├── database.py             # 数据库连接
│   ├── models/                 # SQLAlchemy 数据模型
│   ├── schemas/                # Pydantic 请求/响应模型
│   ├── routers/                # API 路由
│   ├── services/               # 业务逻辑（认证、AI）
│   ├── utils/                  # 工具（密码加密）
│   └── requirements.txt
└── frontend/                   # 前端服务
    ├── nuxt.config.ts          # Nuxt 配置
    ├── app.vue                 # 根组件
    ├── components/             # 公共组件（BottomTabBar、NavBar）
    ├── composables/            # 组合式函数（API、认证）
    ├── layouts/                # 布局（default、auth）
    ├── pages/                  # 页面路由
    ├── stores/                 # Pinia 状态管理
    ├── types/                  # TypeScript 类型定义
    └── middleware/             # 路由中间件
```

## 快速开始 / 初次启动

### 环境要求

| 依赖 | 版本要求 | 说明 |
|---|---|---|
| Python | 3.11+ | 后端运行环境 |
| Node.js | 18+ | 前端运行环境 |
| PostgreSQL | 14+ | 数据存储；也可使用 Docker 提供的 PostgreSQL 实例 |
| Docker（可选） | 20+ | 选择 Docker Compose 启动方式时需要 |

> 提示：如果本地未安装 PostgreSQL 或 MinIO，可使用下方“方式一 Docker Compose”启动基础设施容器。

---

### 方式一：Docker Compose 启动

`docker/docker-compose.infra.yml` 定义了 PostgreSQL 与 MinIO 服务，可启动本地基础设施。

```bash
cd diary-platform
docker compose -f docker/docker-compose.infra.yml up -d
```

生产环境 Docker 部署请参阅 [`docker/部署打包流程.md`](docker/部署打包流程.md)。

> 注意：该 Compose 文件仅启动 PostgreSQL 和 MinIO；应用容器使用生产 Compose 文件部署。

---

### 方式二：本地手动启动（默认）

适用于本地开发调试场景，需自行准备 PostgreSQL、后端、前端三个组件。

#### 步骤 1：准备 PostgreSQL 数据库

确保 PostgreSQL 服务已运行，并创建与后端配置匹配的用户和数据库。以下以创建用户 `postgres`、数据库 `diary_platform` 为例：

```bash
# 使用 psql 连接到 PostgreSQL（按实际安装方式调整连接方式）
psql -U postgres

# 在 psql 交互界面中执行：
CREATE DATABASE diary_platform;

# 如需创建独立应用用户（可选）：
CREATE USER diary_user WITH PASSWORD 'your-password';
GRANT ALL PRIVILEGES ON DATABASE diary_platform TO diary_user;
\q
```

#### 步骤 2：后端配置

进入后端目录，复制环境变量示例文件并编辑：

```bash
cd backend
cp .env.example .env
```

编辑 `.env`，逐项填写（各字段说明见下方"配置项说明"表格）：

```env
# 数据库连接（按实际用户/密码/地址填写）
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/diary_platform

# JWT 签名密钥 —— 执行下方命令生成后填入
SECRET_KEY=<执行: python -c "import secrets; print(secrets.token_urlsafe(32))">

# Fernet 对称加密密钥（用于日记内容加密）—— 执行下方命令生成后填入
ENCRYPTION_KEY=<执行: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">

# DeepSeek API 配置
# 模型 API 地址、密钥和模型选择不再通过 .env 配置。
# 请登录管理端，在模型管理、渠道管理、模型设置中维护。
```

密钥生成命令汇总（在终端执行后将输出值复制到 `.env` 对应字段）：

```bash
# 生成 SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"

# 生成 ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

#### 步骤 3：后端依赖安装

建议使用虚拟环境隔离依赖：

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows 使用: venv\Scripts\activate
pip install -r requirements.txt
backend/venv/bin/python -m pip install -r backend/requirements.txt
```

#### 步骤 4：启动后端

```bash
cd backend
source venv/bin/activate         # 激活虚拟环境
uvicorn main:app --reload --port 8000
```

启动成功后，应用会在启动事件中通过 `Base.metadata.create_all` 自动创建全部数据表，**无需手动执行迁移脚本**。

#### 步骤 5：前端依赖安装与启动

```bash
cd frontend
npm install
npm run dev

cd backend
source venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000

cd frontend
NUXT_APP_BASE_URL=/secret/ \
NUXT_PUBLIC_API_BASE=http://192.168.31.60:8000/diary/api \
npx nuxt dev --host 0.0.0.0 --port 3000

http://192.168.0.65:3000/secret/
```

前端 API 地址已在 `frontend/nuxt.config.ts` 的 `runtimeConfig.public.apiBase` 中配置，默认为 `http://localhost:8000/api`，与本地后端一致，开发环境无需额外配置。前端无需单独的 `.env` 文件。

---

### 访问地址说明

| 服务 | 地址 | 说明 |
|---|---|---|
| 前端页面 | http://localhost:3000 | Nuxt 3 开发服务器 |
| 后端 API 根路径 | http://localhost:8000 | 健康检查接口 |
| 后端 API 文档 | http://localhost:8000/docs | FastAPI 自动生成的 Swagger 交互文档 |

---

### 配置项说明

后端配置通过 `backend/.env` 文件或环境变量注入（由 `backend/config.py` 中的 `Settings` 读取）。各字段如下：

| 字段名 | 必填 | 说明 | 示例值 / 生成方式 |
|---|---|---|---|
| `DATABASE_URL` | 是 | PostgreSQL 连接串，格式 `postgresql+psycopg2://<用户>:<密码>@<host>:<port>/<数据库名>` | `postgresql+psycopg2://postgres:postgres@localhost:5432/diary_platform` |
| `SECRET_KEY` | 是 | JWT 签名密钥，生产环境务必替换为随机值 | 生成命令：`python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `ENCRYPTION_KEY` | 是 | Fernet 对称加密密钥，用于日记内容加密；为空时加密功能不可用 | 生成命令：`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `BACKUP_STORAGE_PATH` | 否 | 定时备份包存储目录；相对路径相对于后端目录 | `backup_packages` |
| `BACKUP_SCHEDULE_TIME` | 否 | 每日定时备份触发时间，格式为 `HH:MM` | `02:00` |
| `BACKUP_SCHEDULE_TIMEZONE` | 否 | 每日定时备份使用的 IANA 时区 | `Asia/Shanghai` |
| 模型调用配置 | 否 | 不再通过 `.env` 配置。请在管理端维护渠道、密钥和用途模型选择。 | 无 |

> 安全提示：以上示例值均为占位符，请勿直接使用。所有密钥请自行生成，`.env` 文件不应提交到版本库。

## 功能模块

当前功能按用户端和管理端组织：

| 端 | 功能 | 状态 |
|---|---|---|
| 用户端 | 账号、日记、AI 整理与分析、语音录入、日程、热词、人物关系 | 已实现 |
| 用户端 | 定期回顾、自我认知、AI 伙伴、独立待办与 OKR、数据飞轮 | 未实现或部分实现 |
| 管理端 | 备份恢复、模型管理、渠道管理、用途及环节模型设置 | 已实现 |

### 底部导航

| Tab | 模块 |
|---|---|
| 日记 | 日记录入、浏览、详情、整理与分析 |
| 日程 | 单次与循环日程 |
| 回顾 | 规划入口，页面未实现 |
| AI伙伴 | 规划入口，页面未实现 |
| 我的 | 热词、人物关系及规划中的自我认知功能 |

## 设计文档

产品设计与需求文档见：[docs/产品设计总纲.md](docs/产品设计总纲.md)。完整文档索引见：[docs/README.md](docs/README.md)。
