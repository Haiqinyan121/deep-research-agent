<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import type { ResearchStore } from "@/composables/useResearch";
import { formatClock } from "@/utils/format";

const props = defineProps<{ store: ResearchStore }>();

const collapsed = ref(false);
const box = ref<HTMLElement | null>(null);

watch(
  () => props.store.logs.length,
  async () => {
    if (collapsed.value) return;
    await nextTick();
    const el = box.value;
    if (!el) return;
    // 只有本来就在底部时才跟着滚，避免用户往回翻历史时被拽走
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }
);
</script>

<template>
  <section class="card log" :class="{ collapsed }">
    <header class="card-head" @click="collapsed = !collapsed">
      <span class="card-title">运行日志</span>
      <span class="count">{{ store.logs.length }}</span>
      <span class="toggle">{{ collapsed ? "展开" : "收起" }}</span>
    </header>

    <div v-show="!collapsed" ref="box" class="stream">
      <p v-if="!store.logs.length" class="line muted">暂无输出。</p>
      <p v-for="entry in store.logs" :key="entry.id" class="line" :class="entry.kind">
        <span class="at">{{ formatClock(entry.at) }}</span>
        <span class="msg">{{ entry.text }}</span>
      </p>
    </div>
  </section>
</template>

<style scoped>
.card-head {
  cursor: pointer;
  user-select: none;
}

.count {
  font-size: 12px;
  color: var(--text-mute);
  font-variant-numeric: tabular-nums;
}

.toggle {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-mute);
}

.stream {
  max-height: 190px;
  overflow-y: auto;
  padding: 12px 18px 14px;
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.7;
}

.collapsed .stream {
  display: none;
}

.line {
  display: flex;
  gap: 10px;
  color: var(--text-dim);
  word-break: break-word;
}

.line + .line {
  margin-top: 2px;
}

.at {
  flex: none;
  color: var(--text-mute);
  opacity: 0.75;
  font-variant-numeric: tabular-nums;
}

.line.ok .msg {
  color: var(--ok);
}

.line.warn .msg {
  color: var(--warn);
}

.line.error .msg {
  color: var(--danger);
}
</style>
