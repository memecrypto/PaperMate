# PaperMate

PaperMate 是 AI 学术论文分析助手，支持论文解析、翻译、术语记忆与自适应对话。

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

## 部署与启动

### Docker 启动

```bash
docker-compose up -d db
docker-compose up -d api

# 可选：启动前端开发服务器
docker-compose --profile dev up -d frontend
```

### 本地开发

```bash
cp backend/.env.example backend/.env
./scripts/dev.sh
```

### 访问

- 前端：http://localhost:5173
- API 文档：http://localhost:8000/docs

## 环境变量（后端）

`backend/.env` 至少需要配置：

- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `OPENAI_API_KEY`
