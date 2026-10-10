<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import QueryPanel from "@/components/QueryPanel.vue";
import StageRail from "@/components/StageRail.vue";
import TaskList from "@/components/TaskList.vue";
import TaskDetail from "@/components/TaskDetail.vue";
import ReportPanel from "@/components/ReportPanel.vue";
import EventLog from "@/components/EventLog.vue";
import { useResearch, type Phase } from "@/composables/useResearch";
import { API_BASE_URL } from "@/services/api";

const store = useResearch();

const PHASE_PILL: Record<Phase, string> = {
  idle: "pill--idle",
  connecting: "pill--run",
  running: "pill--run",
  done: "pill--ok",
  stopped: "pill--warn",
  error: "pill--err"
};

const phasePill = computed(() => PHASE_PILL[store.phase]);

// ---- 主题：初始值由 index.html 里的内联脚本写进 data-theme，避免首屏闪白 ----
const theme = ref<"dark" | "light">(
  document.documentElement.dataset.theme === "light" ? "light" : "dark"
);

function toggleTheme(): void {
  theme.value = theme.value === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = theme.value;
  try {
    localStorage.setItem("dr-theme", theme.value);
  } catch {
    /* 隐私模式下写不了，忽略即可 */
  }
}

let healthTimer: ReturnType<typeof setInterval> | null = null;

onMounted(() => {
  void store.checkHealth();
  healthTimer = setInterval(() => void store.checkHealth(), 20000);
});

onBeforeUnmount(() => {
  if (healthTimer !== null) clearInterval(healthTimer);
  store.stop();
});
</script>

<template>
  <div class="shell">
    <header class="top">
      <div class="brand">
        <span class="logo" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="19" height="19">
            <circle cx="10.5" cy="10.5" r="6.2" fill="none" stroke="currentColor" stroke-width="2" />
            <path d="M15.4 15.4L21 21" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
            <path d="M8 10.5h5M10.5 8v5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
          </svg>
        </span>
        <div class="titles">
          <h1>Deep Research Agent</h1>
          <p>规划 · 并行检索 · 分段摘要 · 汇总成稿</p>
        </div>
      </div>

      <div class="top-right">
        <span class="pill" :class="phasePill">
          <span class="dot" :class="{ breathe: store.busy }"></span>
          {{ store.phaseLabel }}
        </span>
        <button
          type="button"
          class="btn btn-sm btn-ghost"
          :title="theme === 'dark' ? '切换到浅色' : '切换到深色'"
          @click="toggleTheme"
        >
          {{ theme === "dark" ? "浅色" : "深色" }}
        </button>
      </div>
    </header>

    <p v-if="store.serverOnline === false" class="banner warn">
      连不上后端 <code>{{ API_BASE_URL }}</code> —— 请确认 <code>langgraph/src/server.py</code>
      已启动，或用 <code>VITE_API_BASE_URL</code> 指向正确的地址。
    </p>

    <p v-if="store.phase === 'error'" class="banner error">{{ store.errorMessage }}</p>

    <main class="layout">
      <div class="column left">
        <QueryPanel :store="store" />
        <StageRail :store="store" />
        <TaskList :store="store" />
        <EventLog :store="store" />
      </div>

      <div class="column right">
        <TaskDetail :store="store" />
        <ReportPanel :store="store" />
      </div>
    </main>
  </div>
</template>

<style scoped>
.shell {
  min-height: 100%;
  background-image: var(--bg-veil);
  background-repeat: no-repeat;
  background-attachment: fixed;
}

.top {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 24px;
  background: color-mix(in srgb, var(--bg) 82%, transparent);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--border);
}

.brand {
  display: flex;
  align-items: center;
  gap: 11px;
  min-width: 0;
}

.logo {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: none;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  color: #fff;
  box-shadow: 0 8px 20px -10px rgba(91, 140, 255, 0.9);
}

.titles h1 {
  font-size: 15.5px;
  letter-spacing: 0.01em;
}

.titles p {
  font-size: 12px;
  color: var(--text-mute);
}

.top-right {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.banner {
  margin: 14px 24px 0;
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  font-size: 13.5px;
  border: 1px solid transparent;
}

.banner.warn {
  color: var(--warn);
  background: var(--warn-soft);
  border-color: color-mix(in srgb, var(--warn) 35%, transparent);
}

.banner.error {
  color: var(--danger);
  background: var(--danger-soft);
  border-color: color-mix(in srgb, var(--danger) 35%, transparent);
}

.banner code {
  font-size: 12.5px;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(127, 127, 127, 0.16);
}

.layout {
  display: grid;
  grid-template-columns: minmax(300px, 370px) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
  padding: 18px 24px 40px;
  max-width: 1560px;
  margin: 0 auto;
}

.column {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.breathe {
  animation: pulse-ring 1.6s var(--ease) infinite;
}

@media (max-width: 1080px) {
  .layout {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 620px) {
  .top {
    padding: 12px 16px;
  }

  .titles p {
    display: none;
  }

  .layout {
    padding: 14px 16px 32px;
    gap: 12px;
  }

  .banner {
    margin: 12px 16px 0;
  }
}
</style>
