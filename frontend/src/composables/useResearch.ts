/**
 * 研究流程的状态机。
 *
 * 把 SSE 事件流翻译成界面状态，是整个前端的核心：
 *   status              → 事件日志
 *   todo_list           → 子任务列表（覆盖式，规划只产出一次）
 *   task_status         → 单个任务的状态流转
 *   sources             → 该任务命中的来源
 *   task_summary_chunk  → 追加到该任务的流式摘要
 *   final_report        → 最终报告
 *   done / error        → 收尾
 *
 * 所有并发都发生在后端：任务会**同时**推进，所以这里必须按 task_id 分桶，
 * 不能假设事件是按任务顺序到达的。
 */

import { computed, reactive, ref } from "vue";
import {
  pingHealth,
  streamResearch,
  type ResearchEvent,
  type TaskStatus
} from "@/services/api";
import { parseSources, type ParsedSource } from "@/utils/markdown";

export type Phase = "idle" | "connecting" | "running" | "done" | "stopped" | "error";

export interface TaskView {
  id: number;
  title: string;
  intent: string;
  query: string;
  status: TaskStatus;
  /** 已完成的摘要（task_status.completed 带来的完整文本） */
  summary: string;
  /** 流式增量，边收边显示 */
  streamText: string;
  sources: ParsedSource[];
  backend: string;
  error: string;
  startedAt: number | null;
  endedAt: number | null;
}

export interface LogEntry {
  id: number;
  at: number;
  text: string;
  kind: "info" | "ok" | "warn" | "error";
}

export const STAGES = [
  { key: "plan", label: "规划", hint: "拆解主题为可检索子任务" },
  { key: "research", label: "检索与摘要", hint: "并行执行各子任务" },
  { key: "report", label: "汇总成稿", hint: "整合为带引用的报告" }
] as const;

const STATUS_LABEL: Record<TaskStatus, string> = {
  pending: "待执行",
  in_progress: "进行中",
  completed: "已完成",
  failed: "失败",
  skipped: "跳过"
};

const MAX_LOGS = 400;

export function statusLabel(status: TaskStatus): string {
  return STATUS_LABEL[status] ?? status;
}

function normalizeStatus(raw: string | undefined): TaskStatus {
  return raw && raw in STATUS_LABEL ? (raw as TaskStatus) : "pending";
}

function toMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.name === "AbortError" ? "请求已中断" : error.message;
  }
  return String(error);
}

export function useResearch() {
  // ---- 表单 ----
  const topic = ref("");

  // ---- 运行状态 ----
  const phase = ref<Phase>("idle");
  const stageIndex = ref(0);
  const report = ref("");
  const errorMessage = ref("");
  const serverOnline = ref<boolean | null>(null);

  const taskMap = ref(new Map<number, TaskView>());
  const selectedId = ref<number | null>(null);
  const logs = ref<LogEntry[]>([]);

  const startedAt = ref<number | null>(null);
  const endedAt = ref<number | null>(null);
  const now = ref(Date.now());

  let controller: AbortController | null = null;
  let timer: ReturnType<typeof setInterval> | null = null;
  let logSeq = 0;

  // ---------------------------------------------------------------- 派生值

  const tasks = computed<TaskView[]>(() =>
    [...taskMap.value.values()].sort((a, b) => a.id - b.id)
  );

  const activeTask = computed<TaskView | null>(() => {
    const id = selectedId.value;
    if (id === null) return null;
    return taskMap.value.get(id) ?? null;
  });

  const counts = computed(() => {
    const list = tasks.value;
    const done = list.filter((t) => t.status === "completed").length;
    const bad = list.filter((t) => t.status === "failed" || t.status === "skipped").length;
    return { total: list.length, done, bad, running: list.length - done - bad };
  });

  const busy = computed(() => phase.value === "connecting" || phase.value === "running");

  /**
   * 顶部进度条：阶段权重 + 阶段内的任务完成度，让等待不那么空。
   *
   * 注意 `error` / `stopped` 要**沿用**当时的进度，不能归零 ——
   * 中断时列表里躺着几个「已完成」的任务，进度条却缩回 0，前后自相矛盾。
   */
  const progress = computed(() => {
    if (phase.value === "idle") return 0;
    if (phase.value === "connecting") return 3;
    if (phase.value === "done") return 100;
    if (stageIndex.value <= 0) return 8;
    if (stageIndex.value === 1) {
      const { total, done, bad } = counts.value;
      if (!total) return 14;
      return 14 + Math.round(68 * ((done + bad) / total));
    }
    return 86;
  });

  const elapsedMs = computed(() => {
    if (startedAt.value === null) return 0;
    return (endedAt.value ?? now.value) - startedAt.value;
  });

  const phaseLabel = computed(() => {
    switch (phase.value) {
      case "connecting":
        return "连接中";
      case "running":
        return "研究中";
      case "done":
        return "已完成";
      case "stopped":
        return "已停止";
      case "error":
        return "出错";
      default:
        return "待命";
    }
  });

  const totalSources = computed(() =>
    tasks.value.reduce((sum, task) => sum + task.sources.length, 0)
  );

  // ---------------------------------------------------------------- 内部工具

  function pushLog(text: string, kind: LogEntry["kind"] = "info"): void {
    const clean = text.trim();
    if (!clean) return;
    const last = logs.value[logs.value.length - 1];
    if (last && last.text === clean && Date.now() - last.at < 800) return; // 去重抖动
    logs.value.push({ id: ++logSeq, at: Date.now(), text: clean, kind });
    if (logs.value.length > MAX_LOGS) logs.value.splice(0, logs.value.length - MAX_LOGS);
  }

  function ensureTask(id: number, patch: Partial<TaskView> = {}): TaskView {
    let task = taskMap.value.get(id);
    if (!task) {
      task = {
        id,
        title: patch.title || `任务 ${id}`,
        intent: patch.intent || "",
        query: patch.query || "",
        status: "pending",
        summary: "",
        streamText: "",
        sources: [],
        backend: "",
        error: "",
        startedAt: null,
        endedAt: null
      };
      taskMap.value.set(id, task);
    }
    return task;
  }

  /**
   * 合并来源，按 URL 去重、保留先出现的顺序。
   *
   * 为什么用并集而不是覆盖：同一个任务的来源会来两次 —— 先是 `sources` 事件
   * （检索一结束就推），后是 `task_status: completed` 里带的 `sources_summary`。
   * 后端用的是同一个变量，两边内容一致；但万一以后某一侧被截断或改成只带
   * top-N，覆盖会让界面上**已经显示过的来源凭空消失**，并集则只会多不会少。
   */
  function mergeSources(current: ParsedSource[], incoming: ParsedSource[]): ParsedSource[] {
    if (!incoming.length) return current;
    const seen = new Set(current.map((item) => item.url));
    return [...current, ...incoming.filter((item) => !seen.has(item.url))];
  }

  function startTimer(): void {
    stopTimer();
    now.value = Date.now();
    timer = setInterval(() => {
      now.value = Date.now();
    }, 250);
  }

  function stopTimer(): void {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  // ---------------------------------------------------------------- 事件分发

  function handleEvent(event: ResearchEvent): void {
    switch (event.type) {
      case "status": {
        if (phase.value === "connecting") phase.value = "running";
        pushLog(event.message, "info");
        break;
      }

      case "todo_list": {
        if (phase.value === "connecting") phase.value = "running";
        stageIndex.value = 1;
        event.tasks.forEach((raw, index) => {
          const id = typeof raw.id === "number" ? raw.id : index + 1;
          const task = ensureTask(id, {
            title: raw.title,
            intent: raw.intent,
            query: raw.query
          });
          task.title = raw.title || task.title;
          task.intent = raw.intent || task.intent;
          task.query = raw.query || task.query;
        });
        pushLog(`规划完成，共 ${event.tasks.length} 个子任务`, "ok");
        break;
      }

      case "task_status": {
        if (phase.value === "connecting") phase.value = "running";
        stageIndex.value = Math.max(stageIndex.value, 1);
        const task = ensureTask(event.task_id, { title: event.title, intent: event.intent });
        if (event.title) task.title = event.title;
        if (event.intent) task.intent = event.intent;

        task.status = normalizeStatus(event.status);
        if (task.status === "in_progress") {
          task.startedAt ??= Date.now();
          if (selectedId.value === null) selectedId.value = task.id; // 自动跟随第一个开跑的任务
        } else {
          task.endedAt = Date.now();
        }
        if (event.detail) task.error = event.detail;
        if (event.summary) task.summary = event.summary;
        if (event.sources_summary) {
          task.sources = mergeSources(task.sources, parseSources(event.sources_summary));
        }
        // 完成时流式文本已经没有意义，用最终摘要覆盖，避免两者不一致
        if (task.status === "completed") task.streamText = task.summary;
        break;
      }

      case "sources": {
        const task = ensureTask(event.task_id);
        const incoming = parseSources(event.latest_sources);
        task.sources = mergeSources(task.sources, incoming);
        if (event.backend) task.backend = event.backend;
        if (incoming.length) {
          pushLog(`任务 ${event.task_id} 命中 ${incoming.length} 条来源`, "ok");
        }
        break;
      }

      case "task_summary_chunk": {
        ensureTask(event.task_id).streamText += event.content;
        break;
      }

      case "final_report": {
        stageIndex.value = 2;
        report.value = event.report;
        pushLog("报告撰写完成", "ok");
        break;
      }

      case "done": {
        phase.value = phase.value === "error" ? "error" : "done";
        break;
      }

      case "error": {
        errorMessage.value = event.detail || "研究过程中出现未知错误";
        pushLog(errorMessage.value, "error");
        phase.value = "error";
        break;
      }

      default:
        break;
    }
  }

  // ---------------------------------------------------------------- 动作

  function resetState(): void {
    stageIndex.value = 0;
    report.value = "";
    errorMessage.value = "";
    taskMap.value = new Map();
    selectedId.value = null;
    logs.value = [];
    endedAt.value = null;
    startedAt.value = null;
  }

  async function start(): Promise<void> {
    const text = topic.value.trim();
    if (!text || busy.value) return;

    resetState();
    phase.value = "connecting";
    startedAt.value = Date.now();
    startTimer();
    pushLog(`开始研究：${text}`, "info");

    controller = new AbortController();
    try {
      await streamResearch(
        { topic: text },
        { onEvent: handleEvent },
        { signal: controller.signal }
      );
      if (phase.value === "connecting" || phase.value === "running") phase.value = "done";
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        phase.value = "stopped";
        pushLog("已手动停止", "warn");
      } else {
        phase.value = "error";
        errorMessage.value = toMessage(error);
        pushLog(errorMessage.value, "error");
      }
    } finally {
      endedAt.value = Date.now();
      stopTimer();
      controller = null;
    }
  }

  function stop(): void {
    controller?.abort();
    controller = null;
  }

  /** 清空结果，回到可以重新提问的状态（保留输入框里的主题）。 */
  function reset(): void {
    stop();
    stopTimer();
    phase.value = "idle";
    resetState();
  }

  function select(id: number): void {
    selectedId.value = id;
  }

  async function checkHealth(): Promise<void> {
    serverOnline.value = await pingHealth();
  }

  // 用 reactive 包一层：组件里就能直接写 store.topic / store.progress，
  // 不用到处 .value（reactive 会自动解包顶层的 ref）。
  return reactive({
    // 表单
    topic,
    // 状态
    phase,
    phaseLabel,
    stageIndex,
    stages: STAGES,
    progress,
    busy,
    elapsedMs,
    tasks,
    counts,
    activeTask,
    selectedId,
    report,
    errorMessage,
    logs,
    serverOnline,
    totalSources,
    // 动作
    start,
    stop,
    reset,
    select,
    checkHealth
  });
}

export type ResearchStore = ReturnType<typeof useResearch>;
