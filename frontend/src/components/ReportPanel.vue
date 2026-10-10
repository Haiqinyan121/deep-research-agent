<script setup lang="ts">
import { computed, ref } from "vue";
import type { ResearchStore } from "@/composables/useResearch";
import { renderMarkdown } from "@/utils/markdown";
import { countWords, toFileName } from "@/utils/format";

const props = defineProps<{ store: ResearchStore }>();

const copied = ref(false);
let copyTimer: ReturnType<typeof setTimeout> | null = null;

const html = computed(() => renderMarkdown(props.store.report));

const stats = computed(() => {
  const words = countWords(props.store.report);
  return [
    { label: "子任务", value: props.store.counts.total },
    { label: "来源", value: props.store.totalSources },
    { label: "字数", value: words }
  ];
});

async function copy(): Promise<void> {
  try {
    await navigator.clipboard.writeText(props.store.report);
    copied.value = true;
    if (copyTimer) clearTimeout(copyTimer);
    copyTimer = setTimeout(() => {
      copied.value = false;
    }, 1800);
  } catch {
    copied.value = false;
  }
}

function download(): void {
  const blob = new Blob([props.store.report], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = toFileName(props.store.topic);
  anchor.click();
  URL.revokeObjectURL(url);
}
</script>

<template>
  <section class="card report">
    <header class="card-head">
      <span class="card-title">研究报告</span>
      <div v-if="store.report" class="tools">
        <span class="saved">{{ copied ? "已复制" : "" }}</span>
        <button type="button" class="btn btn-sm btn-ghost" @click="copy">复制</button>
        <button type="button" class="btn btn-sm" @click="download">下载 .md</button>
      </div>
    </header>

    <div class="card-body">
      <p v-if="!store.report" class="empty">
        <template v-if="store.busy">
          报告撰写专家正在整合 {{ store.counts.total }} 个子任务的摘要…
        </template>
        <template v-else>研究完成后，最终报告会出现在这里。</template>
      </p>

      <template v-else>
        <div class="prose" v-html="html"></div>
        <footer class="foot">
          <span v-for="item in stats" :key="item.label" class="stat">
            <strong>{{ item.value }}</strong>
            <em>{{ item.label }}</em>
          </span>
        </footer>
      </template>
    </div>
  </section>
</template>

<style scoped>
.tools {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.saved {
  font-size: 12px;
  color: var(--ok);
  min-width: 42px;
  text-align: right;
}

.empty {
  color: var(--text-mute);
  font-size: 13.5px;
  text-align: center;
  padding: 26px 8px;
}

.prose {
  font-size: 15px;
  line-height: 1.8;
}

.foot {
  display: flex;
  gap: 22px;
  margin-top: 22px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

.stat {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.stat strong {
  font-size: 15px;
  font-variant-numeric: tabular-nums;
}

.stat em {
  font-size: 12px;
  font-style: normal;
  color: var(--text-mute);
}
</style>
