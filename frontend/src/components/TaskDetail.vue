<script setup lang="ts">
import { computed } from "vue";
import { statusLabel, type ResearchStore } from "@/composables/useResearch";
import { renderMarkdown, siteLabel } from "@/utils/markdown";

const props = defineProps<{ store: ResearchStore }>();

const task = computed(() => props.store.activeTask);

const streaming = computed(() => task.value?.status === "in_progress");

/** 摘要 + 事件日志里的状态消息拼成最终展示文本（失败时优先显示错误）。 */
const bodyHtml = computed(() => {
  const current = task.value;
  if (!current) return "";
  if (current.status === "failed" && current.error) {
    return renderMarkdown(`**任务执行失败**\n\n\`\`\`\n${current.error}\n\`\`\``);
  }
  const text = current.streamText || current.summary;
  if (!text) return "";
  return renderMarkdown(text);
});

const PILL_CLASS = {
  pending: "pill--idle",
  in_progress: "pill--run",
  completed: "pill--ok",
  failed: "pill--err",
  skipped: "pill--warn"
} as const;
</script>

<template>
  <section class="card detail">
    <header class="card-head">
      <span class="card-title">任务详情</span>
      <span v-if="task" class="pill" :class="PILL_CLASS[task.status]">
        {{ statusLabel(task.status) }}
      </span>
    </header>

    <div class="card-body">
      <p v-if="!task" class="empty">在左侧选择一个子任务，查看它的检索来源与摘要。</p>

      <template v-else>
        <h3 class="title">{{ task.title }}</h3>

        <dl class="meta">
          <div v-if="task.intent">
            <dt>目标</dt>
            <dd>{{ task.intent }}</dd>
          </div>
          <div v-if="task.query">
            <dt>检索式</dt>
            <dd><code>{{ task.query }}</code></dd>
          </div>
          <div v-if="task.backend">
            <dt>后端</dt>
            <dd>{{ task.backend }}</dd>
          </div>
        </dl>

        <div v-if="task.sources.length" class="sources">
          <h5 class="sub">来源 · {{ task.sources.length }}</h5>
          <ul>
            <li v-for="source in task.sources" :key="source.url">
              <a :href="source.url" target="_blank" rel="noopener noreferrer">
                <span class="site">{{ siteLabel(source.url) }}</span>
                <span class="label">{{ source.title }}</span>
              </a>
            </li>
          </ul>
        </div>

        <div class="summary">
          <h5 class="sub">摘要</h5>
          <p v-if="!bodyHtml && streaming" class="waiting">
            <span class="caret"></span>
          </p>
          <p v-else-if="!bodyHtml" class="empty">该任务暂无摘要内容。</p>
          <div v-else class="prose" :class="{ streaming }">
            <div v-html="bodyHtml"></div>
            <span v-if="streaming" class="caret"></span>
          </div>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.empty {
  color: var(--text-mute);
  font-size: 13.5px;
  text-align: center;
  padding: 22px 8px;
}

.waiting {
  padding: 10px 0;
}

.title {
  font-size: 17px;
  margin-bottom: 12px;
}

.meta {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin: 0 0 16px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}

.meta > div {
  display: flex;
  gap: 10px;
  font-size: 13.5px;
  line-height: 1.55;
}

.meta dt {
  flex: none;
  width: 44px;
  color: var(--text-mute);
}

.meta dd {
  margin: 0;
  color: var(--text-dim);
  min-width: 0;
  word-break: break-word;
}

.meta code {
  font-size: 12.5px;
  padding: 1px 6px;
  border-radius: 5px;
  background: var(--surface-3);
  color: var(--text);
}

.sub {
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-mute);
  margin-bottom: 8px;
}

.sources {
  margin-bottom: 18px;
}

.sources ul {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.sources a {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-xs);
  background: var(--surface-2);
  color: var(--text);
  text-decoration: none;
  font-size: 13px;
  transition: border-color var(--dur) var(--ease), background var(--dur) var(--ease);
}

.sources a:hover {
  border-color: var(--accent-line);
  background: var(--surface-3);
  text-decoration: none;
}

.site {
  flex: none;
  font-family: var(--font-mono);
  font-size: 11.5px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--accent-soft);
  color: var(--accent);
}

.label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-dim);
}

.prose {
  font-size: 14.5px;
  line-height: 1.75;
  color: var(--text);
}
</style>
