# Dota 项目交接文档

> **历史文档提示**：本文记录的是原版 MiniMax 单模型实现，部分文件与流程已经过时。当前版本请以 [README.md](README.md) 为准。AI 相关实现已迁移到 `app/services/ai_analyzer.py`、`app/services/llm_client.py`、`app/services/llm_settings.py`，并支持多模型 GUI。

## 1. 项目定位

这是一个基于 FastAPI 的 Dota 2 比赛复盘 Web 应用。

核心能力：

- 用户输入比赛 ID
- 后端从 OpenDota 拉取比赛数据
- 若录像尚未解析，先给基础数据；后续刷新时自动检查是否可升级为完整数据
- 后端对比赛数据做结构化处理
- 再调用兼容 OpenAI SDK 的 MiniMax 接口，为每位玩家生成中文 AI 复盘建议
- 前端以网页形式展示玩家维度的经济、团战、出装、视野、对线、目标控制等信息

目标用户：

- 中文 Dota 玩家
- 希望做单局复盘、找问题、看经济曲线和 AI 建议的人


## 2. 技术栈

- Python 3.x
- FastAPI
- Jinja2
- httpx
- Pydantic v1
- OpenAI Python SDK
- 前端为原生 HTML/CSS/JS，无前端框架


## 3. 运行方式

安装依赖：

```bash
pip install -r requirements.txt
```

配置 `.env`：

```env
MINIMAX_API_KEY=...
MINIMAX_BASE_URL=https://api.minimax.chat/v1
MINIMAX_MODEL=MiniMax-M2.7
```

启动：

```bash
python main.py
```

默认访问：

- `http://127.0.0.1:8000/`


## 4. 目录结构

### 根目录

- `main.py`：FastAPI 入口，挂载静态资源、注册 Jinja2 `tojson` 过滤器、加载路由
- `requirements.txt`：依赖
- `.env` / `.env.example`：环境变量
- `HANDOFF.md`：本交接文档

### app

- `app/config.py`：配置项
- `app/routers/analysis.py`：主业务路由，首页、创建分析任务、查询任务状态、比赛详情页、缓存 JSON API
- `app/models/match.py`：OpenDota 原始比赛数据模型
- `app/models/analysis.py`：结构化分析结果模型
- `app/services/opendota.py`：OpenDota HTTP 客户端、解析状态判断、请求解析、轮询逻辑
- `app/services/data_processor.py`：把原始比赛数据转换成前端可消费的结构化分析模型
- `app/services/claude_analyzer.py`：AI 建议生成逻辑，实际上走的是 MiniMax 兼容接口
- `app/services/cache.py`：本地 JSON 缓存
- `app/services/analysis_jobs.py`：后台分析任务管理器，进程内内存实现
- `app/utils/hero_names.py`：英雄 ID 到中文名的解析入口
- `app/utils/item_names.py`：道具名、段位名解析
- `app/utils/zh_names.py`：本地中文映射表
- `app/utils/rate_limiter.py`：OpenDota 请求限速

### templates

- `templates/base.html`：基础布局
- `templates/index.html`：首页
- `templates/match.html`：比赛详情页
- `templates/error.html`：错误页
- `templates/partials/*.html`：各分析分区组件

### static

- `static/css/style.css`：全站样式
- `static/js/app.js`：页面通用交互、异步分析任务提交与轮询
- `static/js/charts.js`：经济图 SVG 渲染、模式切换、hover 排行面板

### cache

- `cache/matches/*.json`：比赛分析结果缓存


## 5. 核心数据流

### 5.1 首次分析

入口：`POST /analyze`

流程：

1. 校验 `match_id`
2. 如果缓存存在且已是完整数据，直接返回完成状态
3. 如果没有缓存，创建后台任务
4. 首页通过 `/api/jobs/{match_id}` 轮询任务进度
5. 任务完成后前端自动跳转 `/match/{match_id}`

### 5.2 后台任务

后台任务函数在：

- `app/routers/analysis.py` 中的 `_run_analysis_job`

执行流程：

1. 从 OpenDota 拉比赛
2. 判断比赛是否已解析
3. 若首次分析且未解析，调用 `wait_for_parse` 轮询等待一段时间
4. 拉英雄映射和道具映射
5. `DataProcessor` 生成结构化分析结果
6. `ClaudeAnalyzer` 生成 AI 建议
7. 写入缓存

### 5.3 基础数据升级为完整数据

这是当前项目已经实现的重要逻辑。

场景：

- 用户第一次分析时，OpenDota 录像还没解析完成
- 系统先缓存“基础数据”版本

后续行为：

- 用户再次点击分析，或刷新 `/match/{match_id}`
- 如果缓存的 `parse_status != parsed`
- 系统会在后台发起一次“升级检查”任务
- 这个升级检查不会再次长时间阻塞页面
- 如果 OpenDota 已解析成功，就重新生成完整分析并覆盖缓存
- 如果仍未解析，就保留当前基础数据

相关代码：

- `app/routers/analysis.py`
- 关键参数：`force_refresh=True`


## 6. 当前前端功能

### 首页

- 输入比赛 ID
- 点击后异步提交分析任务
- 首页显示任务进度
- 分析完成后自动跳转结果页
- 展示最近分析记录

相关文件：

- `templates/index.html`
- `static/js/app.js`

### 比赛详情页

支持：

- 玩家切换
- 分区切换：经济 / 团战 / 出装 / 视野 / 目标 / 对线
- 返回首页按钮
- 如果当前仅有基础数据，会显示提示，并在后台自动检查解析状态

相关文件：

- `templates/match.html`
- `static/js/app.js`

### 经济图

当前已实现 3 个模式：

1. 所有人
2. 阵营对比
3. 仅当前玩家

“所有人”模式特性：

- 10 名玩家使用高区分度颜色
- 当前玩家高亮

“阵营对比”模式特性：

- 显示天辉总经济 vs 夜魇总经济

hover 特性：

- 鼠标移动到图表上时
- 显示当前时间点的排行列表
- 按经济从高到低排序
- 展示经济值
- tooltip 每一行按阵营染底色

相关文件：

- `templates/partials/economy_section.html`
- `static/js/charts.js`
- `static/css/style.css`


## 7. 缓存机制

缓存实现：

- `app/services/cache.py`

缓存特点：

- 按比赛 ID 写 JSON 文件
- 带 TTL
- 使用临时文件 + `os.replace` 原子写入
- 缓存模型版本控制已开启

当前缓存版本：

- `cache_version = 3`

用途：

- 防止旧结构缓存破坏新页面
- 经济图、购买记录图标、异步升级逻辑都依赖缓存版本正确


## 8. OpenDota 相关实现细节

OpenDota 客户端：

- `app/services/opendota.py`

已实现：

- 请求限速
- 超时重试
- 429 退避重试
- 404 / HTTP 错误封装

解析状态判断：

- 通过玩家是否有 `gold_t` 判定

当前 item 拉取逻辑：

- `fetch_items()` 返回的是 item key，而不是英文显示名
- 这是为了统一走本地中文道具映射


## 9. AI 分析实现细节

AI 实现在：

- `app/services/claude_analyzer.py`

说明：

- 类名叫 `ClaudeAnalyzer`，但实际不是 Claude
- 当前用的是 OpenAI SDK 调 MiniMax 兼容接口
- 这是历史命名遗留

当前行为：

- 并发分析 10 名玩家
- 系统提示词要求输出 JSON
- 做了多层 JSON 提取容错
- 会剥离 `<think>...</think>` 块

注意：

- 文件里仍有一些旧的乱码文本和历史内容
- 但当前逻辑可用


## 10. 中文映射现状

### 英雄名

实际显示使用：

- `app/utils/hero_names.py`
- 优先读取 `app/utils/zh_names.py` 中的 `HERO_ZH`

现状：

- 这张表里存在明显错位
- 例如 `122` 被错误写成了“天涯墨客”
- 按 OpenDota / dotaconstants 当前 ID 体系，`122` 不是正式英雄 ID

建议：

- 下一步优先修 `HERO_ZH`

### 道具名

显示逻辑：

- OpenDota item key -> `ITEM_ZH`

现状：

- 常用道具基本可用
- 但是否完全正确，仍建议继续校验


## 11. 浏览器与缓存注意事项

Chrome 曾出现过：

- 页面功能不正常，但 Edge 正常

根因更像是：

- Chrome 命中了旧静态资源缓存

已做处理：

- 在模板中给 `style.css` / `app.js` / `charts.js` 加了版本号 query string

相关文件：

- `templates/base.html`
- `templates/match.html`

注意：

- `/.well-known/appspecific/com.chrome.devtools.json 404`
- 这是 Chrome DevTools 自己的探测请求
- 不是项目功能错误根因


## 12. 当前已知问题 / 技术债

### 1. 中文映射仍不干净

- 英雄中文名有明显错位
- 道具中文名也可能有不准确项

### 2. 代码里仍有部分历史乱码

- 终端中看到的一些中文乱码，不一定都影响运行
- 但维护体验不好
- 最终建议分阶段清理模板和服务层文案

### 3. 任务系统是内存级

- `analysis_jobs.py` 当前是进程内内存实现
- 适合单机、单进程开发场景
- 如果后续要多进程 / 多实例部署，需要换 Redis / DB 队列

### 4. 没有正式测试体系

- 当前主要依赖手工验证和编译检查
- 没有 pytest / Playwright / 集成测试


## 13. 推荐的后续迭代顺序

### 第一优先级

- 修正整张英雄中文映射表
- 修正整张道具中文映射表

### 第二优先级

- 清理模板与服务层里的历史乱码文案
- 统一页面中文文案

### 第三优先级

- 增加测试
- 至少覆盖：
  - 缓存读写
  - 后台任务状态流
  - OpenDota 解析升级逻辑
  - 经济图数据构造函数

### 第四优先级

- 如需上线，替换内存任务管理为持久化队列


## 14. 关键文件速查

最重要的文件：

- [main.py](/D:/pythonProjects/Dota/main.py)
- [app/routers/analysis.py](/D:/pythonProjects/Dota/app/routers/analysis.py)
- [app/services/analysis_jobs.py](/D:/pythonProjects/Dota/app/services/analysis_jobs.py)
- [app/services/opendota.py](/D:/pythonProjects/Dota/app/services/opendota.py)
- [app/services/data_processor.py](/D:/pythonProjects/Dota/app/services/data_processor.py)
- [app/services/cache.py](/D:/pythonProjects/Dota/app/services/cache.py)
- [app/services/claude_analyzer.py](/D:/pythonProjects/Dota/app/services/claude_analyzer.py)
- [app/utils/zh_names.py](/D:/pythonProjects/Dota/app/utils/zh_names.py)
- [templates/index.html](/D:/pythonProjects/Dota/templates/index.html)
- [templates/match.html](/D:/pythonProjects/Dota/templates/match.html)
- [templates/partials/economy_section.html](/D:/pythonProjects/Dota/templates/partials/economy_section.html)
- [static/js/app.js](/D:/pythonProjects/Dota/static/js/app.js)
- [static/js/charts.js](/D:/pythonProjects/Dota/static/js/charts.js)
- [static/css/style.css](/D:/pythonProjects/Dota/static/css/style.css)


## 15. 接手时建议的第一步

如果下次重新开启对话，只看这份文档，建议按下面顺序接手：

1. 先读 `app/routers/analysis.py`
2. 再读 `app/services/data_processor.py`
3. 再读 `static/js/app.js` 和 `static/js/charts.js`
4. 最后检查 `app/utils/zh_names.py`

如果是继续做功能迭代，优先确认：

- 这次要改的是后端数据流、AI 分析、还是前端展示
- 是否会影响缓存版本
- 是否需要让旧缓存失效


## 16. 一句话总结

这是一个“OpenDota 数据拉取 + 本地结构化处理 + MiniMax AI 中文复盘 + 原生前端展示”的单机版 Dota 复盘工具，核心主链已打通，当前最重要的后续工作是修正中文映射、清理技术债，并在需要时把后台任务系统升级成可持久化方案。
