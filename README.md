# Dota 2 比赛复盘助手

基于 FastAPI 的 Dota 2 比赛复盘 Web 应用，为中文玩家提供 AI 驱动的比赛分析和复盘建议。

## 功能特性

- 比赛 ID 输入，快速获取比赛数据
- 从 OpenDota 拉取比赛数据，支持录像解析状态检测
- 结构化分析：经济、团战、出装、视野、目标控制、对线等维度
- AI 复盘建议：基于 MiniMax 接口生成中文分析
- 经济曲线可视化
- 支持基础数据自动升级为完整数据

## 技术栈

- Python 3.x
- FastAPI
- Jinja2 模板引擎
- httpx (HTTP 客户端)
- Pydantic v1
- OpenAI Python SDK
- 前端：原生 HTML/CSS/JS

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/853qy/dota_analysis.git
cd dota_analysis
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

复制 `.env.example` 为 `.env`，填入你的 API 配置：

```env
MINIMAX_API_KEY=your_api_key_here
MINIMAX_BASE_URL=https://api.minimax.chat/v1
MINIMAX_MODEL=MiniMax-M2.7
```

### 4. 启动服务

```bash
python main.py
```

服务启动后访问：`http://127.0.0.1:8000/`

## 项目结构

```
├── main.py                 # FastAPI 入口
├── requirements.txt        # 依赖列表
├── .env.example           # 环境变量示例
├── HANDOFF.md             # 项目交接文档
│
├── app/
│   ├── config.py          # 配置项
│   ├── routers/           # 路由
│   │   └── analysis.py    # 主业务路由
│   ├── models/            # 数据模型
│   │   ├── match.py       # 比赛数据模型
│   │   └── analysis.py    # 分析结果模型
│   ├── services/          # 业务逻辑
│   │   ├── opendota.py    # OpenDota API 客户端
│   │   ├── data_processor.py    # 数据处理
│   │   ├── claude_analyzer.py   # AI 分析
│   │   ├── cache.py      # 缓存管理
│   │   └── analysis_jobs.py     # 后台任务
│   └── utils/             # 工具函数
│       ├── hero_names.py # 英雄名称
│       ├── item_names.py # 道具名称
│       └── rate_limiter.py    # 请求限速
│
├── templates/             # Jinja2 模板
│   ├── base.html
│   ├── index.html
│   ├── match.html
│   ├── error.html
│   └── partials/         # 组件片段
│
└── static/               # 静态资源
    ├── css/style.css
    └── js/
        ├── app.js
        └── charts.js
```

## 使用说明

1. 在首页输入 Dota 2 比赛 ID（可从游戏客户端或 DotaPlus 获取）
2. 点击分析按钮，系统会拉取并处理比赛数据
3. 等待分析完成，自动跳转到比赛详情页
4. 查看各维度的详细分析和 AI 复盘建议
5. 支持切换不同玩家查看对应分析

## 数据流

1. 用户提交比赛 ID
2. 后端从 OpenDota 获取比赛数据
3. 判断录像是否已解析（未解析时先返回基础数据）
4. 结构化处理比赛数据
5. 调用 MiniMax API 生成 AI 复盘建议
6. 写入本地缓存并返回结果

## 注意事项

- 本地缓存存储在 `cache/matches/` 目录
- `.env` 文件包含敏感 API 密钥，已配置在 `.gitignore` 中
- OpenDota 对未解析录像需要等待一段时间，系统会自动轮询检查