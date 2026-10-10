# Deep Research Agent

输入一个开放主题，系统自动完成 **规划 → 并行检索 → 分段摘要 → 汇总结稿**，输出一份带来源引用的 Markdown 研究报告。

后端用 **LangGraph** 把三类 Agent 编成一张图 —— Planner 拆题、Researcher 并行检索并摘要、Reporter 汇总结稿；前端用 **Vue 3 + TypeScript**，通过 SSE 实时呈现每个子任务的进度、检索来源和正在逐字生成的摘要。整个过程可追溯：报告里的每条引用都能对回它的原始链接。

联网检索固定走 Tavily（失败自动重试）；可选接入本地私有知识库（RAG）。模型服务可接任意 OpenAI 兼容接口（DeepSeek / Qwen / Ollama / LM Studio）。

---

## 一、能做什么

- **一句话出报告** —— 输入主题即可，不用自己拆题，系统会拆成 3~5 个可独立检索的子任务
- **子任务并行执行** —— 各任务同时推进，界面实时显示每个任务是排队、进行中、已完成还是失败
- **过程可见** —— 每个任务命中了哪些来源、摘要正在逐字输出，都能看到
- **报告可带走** —— 输出结构化 Markdown，一键复制或下载 `.md`
- **可查私有文档** —— 可选接入本地知识库，让 Agent 除了联网搜索还能查你自己的资料
- **检索失败自动重试** —— 网络抖动不会让子任务直接失败，重试过程在界面事件日志里可见

前端支持深色 / 浅色主题。后端掉线或接口异常时界面会明确提示，不会静默失败。

---

## 二、快速开始

**环境要求**：Python ≥ 3.11；只用 API / 命令行可以不装 Node。

### 1. 配置

```bash
cd langgraph
cp .env.example .env
```

填入你自己的模型和搜索服务密钥：

| 变量 | 说明 |
|---|---|
| `LLM_PROVIDER` | `custom`（OpenAI 兼容 API）/ `ollama` / `lmstudio` |
| `LLM_MODEL_ID` / `LLM_API_KEY` / `LLM_BASE_URL` | 模型名、密钥、服务地址 |
| `TAVILY_API_KEY` | 搜索服务密钥（必填） |
| `MAX_WEB_RESEARCH_LOOPS` | 研究轮次上限（默认 3） |

> `.env` 已被 `.gitignore` 忽略，**请勿把真实密钥提交上去**。

### 2. 起后端服务

```bash
cd langgraph
uv sync
python src/server.py          # → http://localhost:8000
```

只想起个命令行验证、不启服务：

```bash
cd langgraph/src
python cli.py "Transformer 模型"
```

### 3. 起前端（另开一个终端）

```bash
cd frontend
npm install
npm run dev                   # → http://localhost:5174
```

前端默认请求 `http://localhost:8000`，可用 `VITE_API_BASE_URL` 覆盖。

### 4. 后端接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/research` | 一次性返回完整报告 |
| `POST` | `/research/stream` | SSE 流式推送全过程事件 |
| `GET` | `/healthz` | 健康检查 |

SSE 事件类型：`status` / `todo_list` / `task_status` / `sources` / `task_summary_chunk` / `final_report` / `done` / `error`。每个事件的产出位置与字段见 [`langgraph/README.md`](langgraph/README.md)。

---

## 三、架构

```
                       用户输入主题
                            │
                            ▼
                   ┌─────────────────┐
                   │     Planner     │  拆解为 3~5 个可检索子任务
                   │                 │  严格 JSON 输出：title / intent / query
                   └─────────────────┘
                            │
                            ▼  Send fan-out 并行
        ┌───────────────────────────────────────────────┐
        │              Researcher × N                   │
        │                                               │
        │   SearchTool 检索  →  Summarizer 去重+摘要     │
        │   (Tavily)                   (流式输出)        │
        │                    →  NoteTool 落盘持久化      │
        └───────────────────────────────────────────────┘
                            │
                            ▼  barrier：全部分支跑完才继续
                   ┌─────────────────┐
                   │    Reporter     │  合并各任务摘要
                   │                 │  生成结构化 Markdown 报告
                   └─────────────────┘
                            │
                            ▼  SSE 逐事件推送
                   ┌─────────────────┐
                   │  Vue 3 前端      │  进度条 / 实时日志 / Markdown 渲染
                   └─────────────────┘
```

三个 Agent 各司其职，两个工具负责与外界交互：

- **Planner** —— 把开放主题拆成可独立检索的子任务，避免「一次问一个大问题」
- **Summarizer** —— 对单个子任务的原始搜索结果去重、识别知识空白、生成带引用的摘要
- **Reporter** —— 按逻辑顺序整合所有摘要，补概述、合并重复、统一格式、整理参考来源
- **SearchTool** —— 封装 Tavily 检索，瞬时失败自动重试
- **NoteTool** —— 把中间结果落盘，作为研究的长期记忆，LLM 上下文被截断也不丢

---

## 四、技术栈

| 层 | 技术 |
|---|---|
| 编排 | LangGraph `StateGraph` / `Send` / `MemorySaver` / `create_react_agent` |
| LLM 接入 | `langchain-openai` `ChatOpenAI`（OpenAI 兼容，可接 DeepSeek / Qwen / Ollama / LM Studio） |
| 工具 | `@tool` 装饰器 + 原生 function calling + `ToolNode` |
| 搜索 | Tavily SDK（失败自动重试） |
| 本地知识库 | Chroma + sentence-transformers（BGE 中文 embedding） |
| 服务 | FastAPI + Uvicorn，SSE（`text/event-stream`） |
| 前端 | Vue 3 `script setup` + TypeScript + Vite，**零 UI 依赖**（Markdown 渲染、SSE 客户端、状态机均为自研） |

---

## 五、本地知识库 RAG（可选）

除了联网搜索，还可以给 Agent 接一份**本地私有文档库**。两者是两条并行的检索通道：

| 检索通道 | 何时生效 |
|---|---|
| 联网搜索 | 每个子任务开始时由服务端自动执行，结果作为摘要的输入 |
| `search_local_knowledge_base` | 作为工具挂载给模型，由模型自行决定是否调用；命中的内容体现在摘要正文里 |

### 1. 放文档

把 `.txt` / `.md` / `.pdf` 放进 `langgraph/data/docs/`（该目录已被 `.gitignore` 忽略，**私有文档不会进版本库**）。

### 2. 建索引

```bash
cd langgraph
python src/knowledge_indexer.py            # 首次；会下载 embedding 模型
python src/knowledge_indexer.py --reset    # 清空重建
```

切分用 `RecursiveCharacterTextSplitter`（针对中文调整了分隔符），向量存到 `langgraph/data/chroma/`。重复执行是**幂等**的：切片 id 由「相对路径::序号」决定，重建会覆盖而不是无限追加。

### 3. 开启

在 `langgraph/.env` 里：

```ini
ENABLE_RAG=True
USE_TOOL_CALLING=True
```

> ⚠️ **这两个开关要一起开**。默认的纯 LLM 总结路径不会调用任何工具；只设 `ENABLE_RAG=True`
> 的话，RAG 工具虽然挂上了却不会被触发 —— 图照常跑完、报告照常产出，只是从头到尾没查过本地文档。

### 4. Embedding 选择

| 模式 | 说明 |
|---|---|
| `EMBEDDING_PROVIDER=local`（默认） | 本地 `BAAI/bge-small-zh-v1.5`，离线可用，中文效果好。代价是首次安装要拉 torch（1~2GB） |
| `EMBEDDING_PROVIDER=openai` | 任何 OpenAI 兼容的 embeddings 接口。⚠️ **DeepSeek 没有 embeddings 接口**，需另配 `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` |

⚠️ 建索引和检索**必须用同一个 embedding 模型**。换模型后要 `--reset` 重建，否则新旧向量落在不同空间里，检索结果会毫无意义 —— 而且**不会报错**。

---

## 六、目录结构

```
deep-research-agent/
├── langgraph/                 # ★ 服务端实现
│   ├── README.md              #   服务端实现说明
│   ├── pyproject.toml
│   ├── data/                  #   本地知识库（docs/ 原始文档，chroma/ 索引）
│   └── src/
│       ├── graph.py           #   StateGraph 组装（核心）
│       ├── state.py           #   TypedDict + Annotated reducer
│       ├── nodes.py           #   plan / research / report 三个节点
│       ├── tools.py           #   @tool 定义的搜索与笔记工具
│       ├── rag_tool.py        #   本地知识库检索工具
│       ├── knowledge_indexer.py  # 建索引脚本
│       ├── server.py          #   FastAPI + SSE
│       ├── cli.py             #   命令行冒烟测试
│       └── ...                #   config / prompts / llm / search / utils
└── frontend/                  # Vue 3 + TypeScript
    ├── src/App.vue            #   页面骨架：顶栏 / 左右分栏 / 主题切换
    ├── src/components/        #   QueryPanel 输入 · StageRail 进度 · TaskList 子任务
    │                          #   TaskDetail 任务详情 · ReportPanel 报告 · EventLog 日志
    ├── src/composables/       #   useResearch：SSE 事件 → 界面状态的状态机
    ├── src/services/api.ts    #   SSE 客户端：拆包 / 解析 / 收窄事件类型
    └── src/utils/             #   markdown 渲染（零依赖）· 格式化
```

---


