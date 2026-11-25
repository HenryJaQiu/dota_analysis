# Dota 2 比赛复盘助手（多模型版）

基于 FastAPI 的 Dota 2 比赛复盘 Web 应用。输入比赛 ID 后，从 OpenDota 拉取比赛数据，生成经济、团战、出装、视野、目标控制、对线等维度的结构化分析，并调用任意 OpenAI / Anthropic 兼容的大模型生成中文教练建议。

本项目 fork 自 [853qy/dota_analysis](https://github.com/853qy/dota_analysis)，在原版基础上做了以下改造：

- **不再绑定 MiniMax**：AI 来源、Base URL、API Key、模型均可配置
- **预设 OpenCode Go**：默认使用 `deepseek-v4.1-flash`
- **网页 GUI 配置**：右上角「模型设置」可填写 API Key、拉取模型列表、测试连接、保存配置
- **模型切换立即生效**：新分析直接使用当前模型；已有比赛可一键重新生成 AI 建议
- **协议自适应**：OpenAI 兼容（`/chat/completions`）与 Anthropic 兼容（`/messages`）双协议
- **配置持久化**：保存在本机 `cache/llm_settings.json`，不会提交到 Git

## 功能特性

- 比赛 ID 输入，后台异步分析并实时展示进度
- 从 OpenDota 拉取比赛数据，自动检测录像解析状态
- 结构化分析：经济、团战、出装、视野、目标控制、对线
- 经济曲线可视化（所有人 / 阵营对比 / 当前玩家）
- AI 中文复盘建议，按玩家生成，包含模型标识与生成时间
- 支持基础数据在录像解析完成后自动升级为完整数据
- 多模型 GUI：来源预设、Base URL、API Key、模型列表、连接测试、超时与并发设置
- 已有比赛可用新模型重新生成 AI 建议，不影响已抓取的比赛数据

## 技术栈

- Python 3.10+
- FastAPI + Jinja2
- httpx（OpenDota、模型接口）
- Pydantic v2 + pydantic-settings
- 前端：原生 HTML / CSS / JS，无前端框架

## 快速开始

### 方式一：双击启动（推荐）

直接双击项目根目录的 `启动.bat`（或 `start.bat`）。

首次启动会自动完成：

1. 检查 Python 3.10+
2. 创建 `.venv` 虚拟环境
3. 安装 `requirements.txt` 中的依赖
4. 启动服务
5. 自动打开浏览器 `http://127.0.0.1:8000/`

之后再次双击会跳过安装，直接启动。服务运行在黑色命令行窗口中，按 `Ctrl+C` 或关闭窗口即可停止。

> 如果电脑没有 Python，请先从 [python.org](https://www.python.org/downloads/) 安装 Python 3.10+，安装时勾选 “Add python.exe to PATH”。

### 方式二：手动启动（开发用）

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python main.py
```

打开 `http://127.0.0.1:8000/`。

> 默认只监听 `127.0.0.1`，因为配置文件里会保存 API Key。如果确实需要局域网访问，可在 `.env` 中设置 `APP_HOST=0.0.0.0`，并自行评估风险。启动器会读取 `.env` 中的 `APP_HOST` / `APP_PORT`。

### 3. 在网页里配置模型

1. 点击右上角「⚙ 模型设置」
2. 选择模型来源（默认 **OpenCode Go**）
3. 填写 API Key（OpenCode Go 的 Key 在 [opencode.ai/auth](https://opencode.ai/auth) 获取）
4. 点击「拉取列表」选择模型，默认 `deepseek-v4.1-flash`
5. 点击「测试连接」确认可用，再点「保存设置」
6. 回到首页输入比赛 ID 开始分析

配置会写入 `cache/llm_settings.json`，下次启动自动读取。

## 支持的模型来源

| 来源 | Base URL | 默认模型 | 鉴权 |
| --- | --- | --- | --- |
| OpenCode Go | `https://opencode.ai/zen/go/v1` | `deepseek-v4.1-flash` | Bearer |
| DeepSeek 官方 | `https://api.deepseek.com/v1` | `deepseek-chat` | Bearer |
| MiniMax | `https://api.minimax.chat/v1` | `MiniMax-M2.7` | Bearer |
| OpenAI | `https://api.openai.com/v1` | `gpt-4.1-mini` | Bearer |
| Ollama / 本地 | `http://127.0.0.1:11434/v1` | 自定义 | 可留空 |
| 自定义 | 任意兼容地址 | 手动填写 | 可选 |

### 关于 OpenCode Go 的协议

OpenCode Go 同时提供两种协议：

- DeepSeek / Kimi / GLM / MiMo，以及 GPT / Gemini 等：使用 `/v1/chat/completions`（OpenCode 会把原生 Responses / Gemini 请求翻译成 Chat Completions）
- MiniMax M3、Qwen、Claude：使用 `/v1/messages`

程序默认使用「自动识别」：根据模型名前缀和 Base URL 选择协议。也可以在下拉框中强制指定协议。调用 OpenCode Go 时会自动附带它要求的 `x-opencode-session` 请求头。

## 配置项

网页中可修改的配置：

| 配置 | 说明 | 默认 |
| --- | --- | --- |
| 模型来源 | 预设来源，切换时自动填充 Base URL 和模型 | OpenCode Go |
| 接口协议 | `auto` / `openai` / `anthropic` | `auto` |
| Base URL | 模型服务地址，通常以 `/v1` 结尾 | `https://opencode.ai/zen/go/v1` |
| API Key | 仅保存在本机；留空保存则不修改已有 Key | 空 |
| 模型 | 模型 ID，可从服务端拉取或手动输入 | `deepseek-v4.1-flash` |
| Temperature | 采样温度 | `0.4` |
| 最大输出 tokens | 单次请求上限 | `4096` |
| 请求超时 | 秒 | `180` |
| 并发数 | 同时分析多少名玩家 | `3` |

### 环境变量（可选）

如果不想用网页保存配置，也可以在 `.env` 中提供首次启动的默认值，参考 `.env.example`：

```env
LLM_PROVIDER=opencode-go
LLM_BASE_URL=https://opencode.ai/zen/go/v1
LLM_MODEL=deepseek-v4.1-flash
LLM_API_KEY=sk-...
```

也兼容原有变量：

```env
MINIMAX_API_KEY=...
MINIMAX_BASE_URL=https://api.minimax.chat/v1
MINIMAX_MODEL=MiniMax-M2.7
```

> 网页保存过设置后，`cache/llm_settings.json` 优先于 `.env`。

## 安全说明

- API Key 以明文写入本机 `cache/llm_settings.json`（`cache/` 已在 `.gitignore` 中）。
- 服务默认只监听 `127.0.0.1`，不要在没有额外鉴权的情况下暴露到公网。
- `/api/llm/models` 只会在请求的 Base URL 与已保存地址同源时复用已保存的 Key，避免把 Key 发送到任意第三方域名。
- 网页只会收到打码后的 Key（如 `sk-a…cdef`），不会回显完整 Key。

## 使用说明

1. 首页输入比赛 ID（可从 Dota 2 客户端或第三方战绩站获取）
2. 后台拉取 OpenDota 数据；若录像尚未解析，先展示基础数据，并自动轮询检查
3. 分析完成后跳转详情页，按玩家查看经济、团战、出装、视野、目标、对线
4. 详情页右上角可看到生成 AI 建议所用的模型，并可「用当前模型重新生成建议」
5. 切换模型后，新旧比赛都可重新生成建议，不必重新抓取 OpenDota 数据

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/llm/settings` | 读取当前模型配置（Key 已打码） |
| PUT | `/api/llm/settings` | 保存模型配置 |
| POST | `/api/llm/settings/clear-key` | 清除已保存的 API Key |
| GET | `/api/llm/models` | 拉取模型列表，失败时回退预设列表 |
| POST | `/api/llm/test` | 用当前表单参数做一次真实对话测试 |
| POST | `/analyze` | 提交比赛分析任务 |
| GET | `/api/jobs/{match_id}` | 查询比赛分析进度 |
| GET | `/api/match/{match_id}/data` | 获取结构化分析 JSON |
| POST | `/api/match/{match_id}/reanalyze` | 用当前模型重新生成 AI 建议 |
| GET | `/api/match/{match_id}/reanalyze` | 查询重新生成任务状态 |

## 项目结构

```
├── start.bat                     # 一键启动（英文文件名）
├── 启动.bat                      # 一键启动（中文文件名）
├── scripts/launcher.py           # 启动器：读取端口、等待服务、打开浏览器
├── main.py                       # FastAPI 入口
├── requirements.txt
├── requirements-dev.txt
├── .env.example
│
├── app/
│   ├── config.py                 # 环境变量与默认配置
│   ├── routers/
│   │   ├── analysis.py           # 比赛分析、进度、重新生成建议
│   │   └── llm.py                # 模型设置、模型列表、连接测试
│   ├── models/
│   │   ├── match.py              # OpenDota 原始数据模型
│   │   └── analysis.py           # 结构化分析结果模型
│   ├── services/
│   │   ├── opendota.py           # OpenDota 客户端
│   │   ├── data_processor.py     # 数据清洗与结构化
│   │   ├── ai_analyzer.py        # 提示词、JSON 解析、AI 建议
│   │   ├── llm_client.py         # OpenAI / Anthropic 双协议传输
│   │   ├── llm_settings.py       # 模型配置持久化与预设
│   │   ├── cache.py              # 本地 JSON 缓存（版本 4）
│   │   └── analysis_jobs.py      # 进程内任务管理
│   └── utils/                    # 英雄 / 道具中文名、限速
│
├── templates/                    # 页面与模型设置弹窗
├── static/js/settings.js         # 模型设置 GUI
└── tests/                        # 解析与配置单元测试
```

## 测试

```bash
pip install -r requirements-dev.txt
pytest -q
```

## 数据流

1. 用户在首页提交比赛 ID
2. 后端从 OpenDota 获取比赛数据并判断解析状态
3. `DataProcessor` 生成结构化分析
4. `AIAnalyzer` 读取当前模型配置，并发调用模型接口生成每位玩家的建议
5. 结果写入 `cache/matches/{match_id}.json`
6. 详情页展示数据、图表、AI 建议及所用模型

如果 AI 调用失败：

- 比赛数据仍会保存，详情页会显示具体错误
- 已存在建议的比赛重新生成失败时，会保留原有建议
- 常见错误（401 / 403 / 404 / 429 / 超时）会在 UI 中给出中文提示

## 从原项目升级

- 依赖已升级到 Pydantic v2 / 新版 FastAPI，请重新安装 `requirements.txt`
- 缓存版本提升到 `4`，旧缓存会自动失效并重新分析
- 原有 `MINIMAX_API_KEY` 配置仍兼容；未显式设置 `LLM_PROVIDER` 时会自动沿用 MiniMax
- 原 `claude_analyzer.py` 已替换为 `ai_analyzer.py`，逻辑不再绑定具体厂商

## 发布到自己的 GitHub

当前目录保留着原仓库的 Git 历史，并已创建分支 `feature/multi-provider-gui`。在 GitHub 上 fork 原仓库后：

```bash
git remote add mine https://github.com/<你的用户名>/dota_analysis.git
git push -u mine feature/multi-provider-gui
```

## 注意事项

- 本地缓存位于 `cache/matches/`，默认 TTL 24 小时
- OpenDota 对未解析录像需要等待，系统会自动轮询
- 进程内任务管理适合单机使用；多实例部署需要换成 Redis / 队列
- 模型返回非 JSON 内容时，会降级为原始文本展示并在页面提示
