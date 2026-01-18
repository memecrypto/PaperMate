# 🎓 PaperMate - Your AI Academic Paper Assistant

### Effortlessly analyze and translate research papers.

![PaperMate](./image.png)

## 🚀 Features Overview

### 1. 📄 Paper Analysis and Translation

- Analyze papers and translate them while maintaining their format.
- Read side-by-side in English and Chinese.
- Use the ReAct Agent framework to automatically retrieve background and motivation.
- Output links to closely related papers, with explanations of their relevance.
- Deeply analyze core innovations: what they are, why they matter, and how they compare to existing methods.
- Present experimental results, including advantages and limitations.
- Suggest feasible future directions based on AI insights.

### 2. 📚 Term Memory and Global Highlighting

- Highlight terms by selecting them to trigger AI-based analysis.
- The parsed terms will be globally highlighted within the project.
- Hover over the terms to see explanations and context.

### 3. 🗣️ User-Profile Driven Paper Conversations

- Update user profile automatically during conversations.
- The AI adjusts the depth and style of responses based on the profile.

## 🚀 Getting Started

### 📦 Visit this page to download

You can download PaperMate from the Releases page here: [Download PaperMate](https://github.com/memecrypto/PaperMate/releases)

### 🏗️ Method 1: Quick Start with Docker (Recommended)

**Using Docker Database**:
```bash
cp backend/.env.example backend/.env
# Edit backend/.env and set DATABASE_URL to:
# DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/papermate

docker-compose --profile db --profile dev up -d
```

**Using External Database**:
```bash
cp backend/.env.example backend/.env
# Edit backend/.env and set DATABASE_URL to your database address

docker-compose --profile dev up -d
```

**Access the Application**:
- Frontend: [http://localhost:5173](http://localhost:5173)
- Backend API: [http://localhost:8000/docs](http://localhost:8000/docs)

**First Time Use**:
1. Visit the frontend [http://localhost:5173](http://localhost:5173).
2. Click on "Register" to create your first user (automatically becomes an admin).
3. After registering, other users cannot register on their own. An admin must add them.

### 🖥️ Method 2: Local Development Start

**Prerequisites**:
- Install Python 3.8 or higher.
- Install the required packages using pip:
```bash
pip install -r requirements.txt
```

**Run the Application**:
1. Ensure your database is set up.
2. Start the server by running:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```
3. Access the frontend at [http://localhost:5173](http://localhost:5173).

## 🛠️ Requirements

- **Operating System**: Windows, macOS, or Linux.
- **Memory**: At least 4GB RAM.
- **Storage**: Minimum of 500MB available disk space.

## 📥 Download & Install

Visit this page to download PaperMate: [Download PaperMate](https://github.com/memecrypto/PaperMate/releases)

## 📘 Support

If you have questions or need help, please check the Issues section on GitHub or open a new issue.

## 👥 Contributing

We welcome contributions. Please see the CONTRIBUTING.md file for details on how to help improve PaperMate. 

## 🔗 License

This project is licensed under the MIT License. See the LICENSE file for more information.