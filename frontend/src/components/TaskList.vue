<script setup lang="ts">
import { computed } from "vue";
import { statusLabel, type ResearchStore, type TaskView } from "@/composables/useResearch";

const props = defineProps<{ store: ResearchStore }>();

const PILL_CLASS: Record<TaskView["status"], string> = {
  pending: "pill--idle",
  in_progress: "pill--run",
  completed: "pill--ok",
  failed: "pill--err",
  skipped: "pill--warn"
};

const summary = computed(() => {
  const { total, done, bad } = props.store.counts;
  if (!total) return "";
  const parts = [`${done}/${total} 完成`];
  if (bad) parts.push(`${bad} 未产出`);
  return parts.join(" · ");
});
</script>

<template>
  <section class="card tasks">
    <header class="card-head">
      <span class="card-title">子任务</span>
      <span v-if="summary" class="count">{{ summary }}</span>
    </header>

    <div class="card-body">
      <p v-if="!store.tasks.length" class="empty">
        <template v-if="store.busy">规划专家正在拆解主题…</template>
        <template v-else>输入主题后，这里会出现拆解出的子任务。</template>
      </p>

      <ul v-else class="list">
        <li
          v-for="task in store.tasks"
          :key="task.id"
          class="item"
          :class="{ selected: task.id === store.selectedId, [task.status]: true }"
          @click="store.select(task.id)"
        >
          <span class="index">{{ String(task.id).padStart(2, "0") }}</span>
          <div class="main">
            <h4 class="title">{{ task.title }}</h4>
            <p v-if="task.intent" class="intent">{{ task.intent }}</p>
          </div>
          <span class="pill" :class="PILL_CLASS[task.status]">
            <span v-if="task.status === 'in_progress'" class="dot breathe"></span>
            <span v-else class="dot"></span>
            {{ statusLabel(task.status) }}
          </span>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.count {
  margin-left: auto;
  font-size: 12.5px;
  color: var(--text-mute);
  font-variant-numeric: tabular-nums;
}

.empty {
  color: var(--text-mute);
  font-size: 13.5px;
  text-align: center;
  padding: 18px 6px;
}

.list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--dur) var(--ease), border-color var(--dur) var(--ease),
    transform var(--dur) var(--ease);
  animation: rise 320ms var(--ease) both;
}

.item:hover {
  background: var(--surface-2);
}

.item.selected {
  background: var(--accent-soft);
  border-color: var(--accent-line);
}

.item.in_progress {
  background: var(--surface-2);
}

.index {
  flex: none;
  margin-top: 1px;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 700;
  color: var(--text-mute);
  font-variant-numeric: tabular-nums;
}

.item.selected .index {
  color: var(--accent);
}

.main {
  flex: 1;
  min-width: 0;
}

.title {
  font-size: 14px;
  font-weight: 570;
  line-height: 1.45;
}

.intent {
  margin-top: 2px;
  font-size: 12.5px;
  color: var(--text-mute);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.pill {
  flex: none;
  margin-top: 1px;
}

.breathe {
  animation: pulse-ring 1.6s var(--ease) infinite;
}
</style>
