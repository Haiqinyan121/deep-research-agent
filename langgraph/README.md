# 服务端实现说明

服务端用 **LangGraph** 编排整条研究流水线：`StateGraph` 组图，`Send` 把子任务派发成并行分支，`Annotated` reducer 合并并发写回的状态，节点内部通过 `get_stream_writer()` 把事件推给 SSE。

这份文档说明服务端的目录结构、运行方式、图是怎么搭的、各配置项的作用，以及 SSE 事件协议。环境配置与前端启动方式见[根目录 README](../README.md)。

---

## 一、目录结构

```
langgraph/
├── README.md              ← 本文件
├── pyproject.toml
├── .env.example
├── data/                  # 本地知识库：docs/ 原始文档，chroma/ 向量索引
└── src/
    ├── graph.py           ← ★ StateGraph 组装（核心）
    ├── state.py           ← ★ TypedDict + Annotated reducer
    ├── nodes.py           ← ★ 三个节点：plan / research / report
    ├── tools.py           ← ★ @tool 装饰器定义工具
    ├── rag_tool.py        ← 本地知识库检索工具（ENABLE_RAG=True 时挂载）
    ├── knowledge_indexer.py ← 建索引脚本（文档 → 向量库）
    ├── server.py          ← FastAPI + SSE
    ├── cli.py             ← 命令行冒烟测试
    ├── llm.py             ← ChatOpenAI 工厂
    ├── search.py          ← 搜索客户端（Tavily，带重试）
    ├── config.py          ← 配置
    ├── prompts.py         ← Prompt 模板
    └── utils.py           ← 去重 / 截断 / 格式化（纯函数）
```

---

## 二、怎么跑

```bash
# 命令行冒烟测试（最快，不需要前端）
cd langgraph/src
python cli.py "Transformer 模型"

# 起后端服务
python src/server.py            # → http://localhost:8000
```

客户端传入的主题、轮次等参数由 `config.py` 从环境变量读取，`.env.example` 里列出了全部可配置项。

---

## 三、图是怎么搭的

```
START → plan ──Send──▶ research ×N ──▶ report → END
                                        ▲
                        barrier：全部分支结束才继续
```

节点名与代码一致（`graph.py` 中注册）：

```python
builder.add_node("plan", ...)
builder.add_node("research", ...)
builder.add_node("report", ...)

builder.add_edge(START, "plan")
builder.add_conditional_edges("plan", fan_out_research, ["research"])   # 动态 fan-out
builder.add_edge("research", "report")                                  # barrier
builder.add_edge("report", END)
```

### 1. 子任务并行：`Send`

`plan` 节点产出子任务列表后，条件边 `fan_out_research` 返回一组 `Send`，每个 `Send` 就是一个独立的 `research` 分支实例：

```python
return [Send("research", {"topic": state["topic"], "task": task}) for task in tasks]
```

分支的启动、等待与结果聚合都由框架负责。所有 `Send` 出去的分支跑完，才触发下游的 `report` 节点 —— 这就是 barrier 语义，也是 `report` 能确定地拿到全部结果的原因。

### 2. 并发状态合并：`Annotated` reducer

多个 `research` 分支会并发把结果写回同一个列表。LangGraph 的做法是**声明合并规则**，而不是加锁：

```python
class ResearchState(TypedDict):
    results: Annotated[list[TaskItem], operator.add]   # 并行分支的返回值自动拼接
```

需要注意的是：某个字段**没有**声明 reducer 时，多个分支同时写它会报 `InvalidUpdateError` —— 框架不会替你猜合并策略，必须显式声明。

### 3. 流式事件：产出下沉到节点

事件在节点内部产生，节点不需要知道 SSE 是怎么发的：

```python
from langgraph.config import get_stream_writer

writer = get_stream_writer()
writer({"type": "task_summary_chunk", "task_id": tid, "content": text})
```

服务端用 `graph.stream(stream_mode=["custom", "updates"])` 同时消费自定义事件与节点更新。编排（`graph.py`）与事件产出（`nodes.py`）因此是解耦的：加一类新事件不需要动图，改图结构也不需要动节点。

### 4. 三个节点分别做什么

| 节点 | 职责 | 产出的事件 |
|---|---|---|
| `plan` | 调用 LLM 把主题拆成 3~5 个子任务（`title` / `intent` / `query`），解析为结构化列表 | `status`、`todo_list` |
| `research` | 由 `Send` 派发，每个实例先搜索、再流式摘要；单个任务失败只标记该任务，不拖垮整张图 | `status`、`task_status`、`sources`、`task_summary_chunk` |
| `report` | 汇总全部任务的摘要与来源，生成结构化 Markdown 报告 | `status`、`final_report` |

---

## 四、配置项

`config.py` 定义了全部字段，环境变量同名大写即可覆盖。常用开关：

| 变量 | 默认 | 作用 |
|---|---|---|
| `ENABLE_NOTES` | `True` | 是否启用笔记工具（把中间结果落盘，作为长期记忆） |
| `ENABLE_RAG` | `False` | 是否挂载本地知识库检索工具 |
| `USE_TOOL_CALLING` | `False` | 摘要阶段用 `create_react_agent`（可调用工具）而非纯 LLM |
| `STRIP_THINKING_TOKENS` | `True` | 是否剥离模型输出里的 `<think>` 段 |
| `FETCH_FULL_PAGE` | `True` | 是否抓取网页全文（关闭则只用搜索摘要） |
| `MAX_WEB_RESEARCH_LOOPS` | `3` | 研究轮次上限（预留字段，尚未接入条件边） |
| `EMBEDDING_PROVIDER` | `local` | `local`（本地 BGE 模型）/ `openai`（OpenAI 兼容接口） |
| `RAG_TOP_K` / `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` | `3` / `800` / `120` | 检索片段数、切片长度、切片重叠 |

> ⚠️ `ENABLE_RAG=True` 需要同时设 `USE_TOOL_CALLING=True`。
> `USE_TOOL_CALLING=False`（默认）时摘要走纯 LLM 路径，**不向模型传任何工具**，
> 挂载的 RAG 与笔记工具都不会被调用；此时图仍会正常跑完并产出报告。

---

## 五、SSE 事件协议

`POST /research/stream` 按 `text/event-stream` 推送，每个事件是一段 `data: {json}`，事件之间以空行分隔。前端按 payload 里的 `type` 字段分发。

| `type` | 产出位置 | 关键字段 |
|---|---|---|
| `status` | 各节点 | `message`、`step`、可选 `task_id` |
| `todo_list` | `plan` | `tasks[]`：`id` / `title` / `intent` / `query` |
| `task_status` | `research` | `task_id`、`status`（`in_progress` / `completed` / `failed` / `skipped`）、可选 `summary` / `sources_summary` / `detail` |
| `sources` | `research` | `task_id`、`latest_sources`（格式化后的来源列表）、`backend` |
| `task_summary_chunk` | `research` | `task_id`、`content`（流式增量文本） |
| `final_report` | `report` | `report`（完整 Markdown） |
| `done` | `server` | 流正常结束 |
| `error` | `server` | `detail` |

`done` 与 `error` 是终态事件，收到即代表本次流结束。
