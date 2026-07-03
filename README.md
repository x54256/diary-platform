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
├── docker-compose.yml          # 容器编排
├── backend/                    # 后端服务
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 配置管理
│   ├── database.py             # 数据库连接
│   ├── models/                 # SQLAlchemy 数据模型
│   ├── schemas/                # Pydantic 请求/响应模型
│   ├── routers/                # API 路由
│   ├── services/               # 业务逻辑（认证、AI）
│   ├── utils/                  # 工具（密码加密）
│   ├── Dockerfile
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

> 提示：如果本地未安装 PostgreSQL，可使用下方"方式一 Docker Compose"自动启动一个 PostgreSQL 15 容器，无需单独安装数据库。

---

### 方式一：Docker Compose 启动

项目根目录下的 `docker-compose.yml` 定义了 `postgres` 与 `backend` 两个服务，可一键拉起数据库与后端。

```bash
cd diary-platform
docker compose up -d
```

启动后：

- `postgres` 容器：PostgreSQL 15，端口 `5432`，用户名 `postgres`，密码 `postgres`，数据库 `diary_platform`，数据持久化于 `postgres_data` 卷。
- `backend` 容器：FastAPI 服务，端口 `8000`，启动时自动创建数据表。

⚠️ **重要提示（启动前务必修改）：**

`docker-compose.yml` 中 `backend` 服务的以下两个环境变量当前为空值，**必须补充后才能完整使用对应功能**：

1. `ENCRYPTION_KEY`：为空时用户密码
2. 加密功能不可用。请在 `docker-compose.yml` 的 `backend.environment` 中填入通过以下命令生成的密钥：

   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

2. `DEEPSEEK_API_KEY`：为空时 AI 整理 / AI 伙伴功能不可用。请在 [DeepSeek 开放平台](https://platform.deepseek.com) 申请 API 密钥（`sk-` 开头）后填入。

另外建议将默认的 `SECRET_KEY` 替换为自行生成的密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

> 注意：`docker-compose.yml` 未定义前端服务。使用 Docker 启动数据库与后端后，前端仍需按"方式二·步骤5"本地启动。

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
DEEPSEEK_API_KEY=your-deepseek-api-key-here
DEEPSEEK_API_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-v4-flash
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
| `DEEPSEEK_API_KEY` | 是 | DeepSeek 平台 API 密钥，`sk-` 开头；在 https://platform.deepseek.com 申请 | `sk-your-deepseek-api-key-here` |
| `DEEPSEEK_API_URL` | 否 | DeepSeek API 地址，默认 `https://api.deepseek.com/v1` | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | 否 | DeepSeek 模型名称，可在 DeepSeek 平台查看可用模型列表 | `deepseek-v4-flash` |

> 安全提示：以上示例值均为占位符，请勿直接使用。所有密钥请自行生成，`.env` 文件不应提交到版本库。

## 功能模块

平台包含 10 个功能模块，分 6 个阶段实施：

| 阶段 | 模块 | 状态 |
|---|---|---|
| 阶段一·日记核心 | 模块一（记录与整理）+ 模块二（浏览与查找）+ 模块三（日记详情） | 开发中 |
| 阶段二·定期回顾 | 模块四（定期回顾） | 待开发 |
| 阶段三·自我认知 | 模块五（人物画像）+ 模块六（心路历程）+ 模块七（认知洞察） | 待开发 |
| 阶段四·AI 伙伴 | 模块八（AI 伙伴） | 待开发 |
| 阶段五·行动管理 | 模块九（待办事项）+ 模块十（目标管理 OKR） | 待开发 |
| 阶段六·数据飞轮 | 全平台闭环 | 待开发 |

### 底部导航

| Tab | 模块 |
|---|---|
| 日记 | 模块一 + 模块二 + 模块三 |
| 回顾 | 模块四 |
| AI伙伴 | 模块八 |
| 我的 | 模块五 + 模块六 + 模块七 + 设置 |

## 设计文档

详细产品设计规格见：[docs/2026-07-02-diary-platform-design.md](../docs/superpowers/specs/2026-07-02-diary-platform-design.md)
