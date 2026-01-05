# PaperMate

PaperMate 是 AI 学术论文分析助手，支持论文解析、翻译、术语记忆与自适应对话。

![PaperMate](./image.png)

## 功能简介

### 1. 论文解析与翻译（保留格式）

- 论文解析为 Markdown 后进行翻译，结构与公式不丢失
- 中英对照阅读界面
- 翻译采用 ReAct Agent 架构：结合 arXiv 与网络检索，补充背景、动机与切入点
- 输出强相关论文链接，并给出相关性说明
- 深度解析核心创新点：是什么、为什么重要、与已有方法对比、关键模块细节
- 给出实验结果、优势与局限性
- 提供 AI 推断的可行未来方向

### 2. 术语记忆与全局高亮

- 划词触发 AI 解析专业术语
- 解析后在项目内全局高亮
- 鼠标悬停显示术语解释与上下文

### 3. 用户画像驱动的论文对话

- 对话中自动更新用户画像
- AI 根据画像实时调整回答深度与表达方式

## 快速开始

### 方式一：Docker 一键启动（推荐）

**使用 Docker 数据库**：
```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env，DATABASE_URL 配置为：
# DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/papermate

docker-compose --profile db --profile dev up -d
```

**使用外部数据库**：
```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env，DATABASE_URL 配置为你的数据库地址

docker-compose --profile dev up -d
```

访问：
- 前端：http://localhost:5173
- 后端 API：http://localhost:8000/docs

**首次使用**：
1. 访问前端 http://localhost:5173
2. 点击注册，创建第一个用户（自动成为管理员）
3. 注册后，其他用户无法自行注册，需要管理员添加

### 方式二：本地开发启动

**前置条件**：
- Python 3.11+
- Node.js 18+
- PostgreSQL 数据库（可以是本地安装或 Docker）

**步骤**：

```bash
# 1. 启动数据库（可选，如果没有 PostgreSQL）
docker-compose --profile db up -d
# 数据库地址：localhost:5433

# 2. 配置环境变量
cp backend/.env.example backend/.env
# 编辑 backend/.env，配置数据库连接和 API 密钥
# 如果使用上面的 Docker 数据库，DATABASE_URL 配置为：
# DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/papermate

# 3. 安装后端依赖
pip install -r backend/requirements.txt

# 4. 安装前端依赖
cd frontend && npm install && cd ..

# 5. 一键启动前后端（自动运行迁移）
./scripts/dev.sh
```

访问：
- 前端：http://localhost:5173
- 后端 API：http://localhost:8000/docs

**首次使用**：
1. 访问前端 http://localhost:5173
2. 点击注册，创建第一个用户（自动成为管理员）
3. 注册后，其他用户无法自行注册，需要管理员添加

## 环境变量配置

编辑 `backend/.env`，配置以下必需项：

```bash
# 数据库连接
# Docker 环境（使用 Docker 数据库）：DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/papermate
# 本地环境（使用外部数据库）：DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/papermate
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/papermate

# JWT 密钥（生产环境必须修改！）
JWT_SECRET_KEY=your-super-secret-key-change-in-production

# OpenAI API（必需）
OPENAI_API_KEY=your-openai-api-key-here
OPENAI_MODEL=gpt-4o

# MinerU PDF 解析（推荐使用云端 API）
MINERU_USE_CLOUD=true
MINERU_API_URL=https://mineru.net
MINERU_API_KEY=your-mineru-api-key

# Tavily 搜索（可选）
TAVILY_API_KEY=your-tavily-api-key-here
```

## 数据库说明

### 使用 Docker 数据库

```bash
# 单独启动数据库
docker-compose --profile db up -d

# 或与其他服务一起启动
docker-compose --profile db --profile dev up -d
```

数据库地址：
- Docker 内部：`db:5432`
- 宿主机访问：`localhost:5433`

### 使用自己的数据库

确保数据库已安装 **pgvector** 扩展：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

然后在 `.env` 中配置你的数据库连接地址。
