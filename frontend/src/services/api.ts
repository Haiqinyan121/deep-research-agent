/**
 * 后端接口客户端。
 *
 * 后端把整条研究流水线包成 SSE：每个事件是一段 `data: {json}`，
 * 事件之间用空行分隔，前端按 payload 里的 `type` 分发。
 * 这里只负责协议层 —— 拆包、解析、把半截 JSON 挡在门外；
 * 「哪个事件该改哪块状态」交给 composables/useResearch.ts。
 */

export type TaskStatus = "pending" | "in_progress" | "completed" | "failed" | "skipped";

export interface RawTask {
  id?: number;
  title?: string;
  intent?: string;
  query?: string;
  status?: string;
}

export interface StatusEvent {
  type: "status";
  message: string;
  step?: number;
  task_id?: number;
}

export interface TodoListEvent {
  type: "todo_list";
  tasks: RawTask[];
  step?: number;
}

export interface TaskStatusEvent {
  type: "task_status";
  task_id: number;
  status: TaskStatus;
  title?: string;
  intent?: string;
  summary?: string;
  sources_summary?: string;
  detail?: string;
  step?: number;
}

export interface SourcesEvent {
  type: "sources";
  task_id: number;
  latest_sources?: string;
  raw_context?: string;
  backend?: string;
  step?: number;
}

export interface SummaryChunkEvent {
  type: "task_summary_chunk";
  task_id: number;
  content: string;
  step?: number;
}

export interface FinalReportEvent {
  type: "final_report";
  report: string;
  step?: number;
}

export interface DoneEvent {
  type: "done";
}

export interface ErrorEvent {
  type: "error";
  detail?: string;
}

export type ResearchEvent =
  | StatusEvent
  | TodoListEvent
  | TaskStatusEvent
  | SourcesEvent
  | SummaryChunkEvent
  | FinalReportEvent
  | DoneEvent
  | ErrorEvent;

export interface ResearchRequest {
  topic: string;
}

/** 终态事件：收到就说明这次流结束了。 */
function isTerminal(event: ResearchEvent): boolean {
  return event.type === "done" || event.type === "error";
}

/** 把 JSON 收窄成已知事件；不认识的结构直接丢掉，不让它污染状态。 */
function parseEvent(raw: string): ResearchEvent | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!data || typeof data !== "object") return null;
  const type = (data as { type?: unknown }).type;
  return typeof type === "string" ? (data as ResearchEvent) : null;
}

const EVENT_SEPARATOR = /\r?\n\r?\n/;

export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export interface StreamHandlers {
  onEvent: (event: ResearchEvent) => void;
}

export interface StreamOptions {
  signal?: AbortSignal;
}

/** 后端活着吗？用于页面右上角的连接指示。 */
export async function pingHealth(options: StreamOptions = {}): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/healthz`, {
      method: "GET",
      signal: options.signal
    });
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * 发起一次流式研究。函数返回时说明**流已经结束**
 * （正常收到 done、收到 error，或被调用方 abort），而不是「请求已发出」。
 */
export async function streamResearch(
  payload: ResearchRequest,
  handlers: StreamHandlers,
  options: StreamOptions = {}
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/research/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream"
    },
    body: JSON.stringify(payload),
    signal: options.signal
  });

  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(detail.trim() || `服务端返回 ${response.status}`);
  }

  const body = response.body;
  if (!body) {
    throw new Error("当前浏览器不支持流式响应（ReadableStream 不可用）");
  }

  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let terminated = false;

  /** 消费一个事件块；如果它是终态事件，返回 true。 */
  const consumeBlock = (block: string): boolean => {
    // 一个事件块里可能有多行 data:，按规范用换行拼起来再解析
    const data = block
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim())
      .join("\n");
    if (!data) return false; // 注释行（`: keepalive`）之类，跳过

    const event = parseEvent(data);
    if (!event) return false;

    handlers.onEvent(event);
    return isTerminal(event);
  };

  /** 把缓冲区里已经完整的事件全部消费掉；遇到终态事件返回 true。 */
  const drain = (): boolean => {
    for (;;) {
      const match = EVENT_SEPARATOR.exec(buffer);
      if (!match) return false;

      const block = buffer.slice(0, match.index);
      buffer = buffer.slice(match.index + match[0].length);
      if (consumeBlock(block)) return true;
    }
  };

  try {
    while (!terminated) {
      const { value, done } = await reader.read();
      if (done) {
        buffer += decoder.decode();
        // 收尾：最后一个事件可能没有以空行结束，按规范仍要派发
        if (!drain() && buffer.trim()) consumeBlock(buffer);
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      terminated = drain();
    }
  } finally {
    // 提前 return（收到终态事件）时主动断开，别让连接挂着
    reader.cancel().catch(() => undefined);
  }
}
