<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from "vue";
import type { ResearchStore } from "@/composables/useResearch";

const props = defineProps<{ store: ResearchStore }>();

const EXAMPLES = [
  "Transformer 架构是怎么演进到今天的大模型的",
  "2025 年 AI Agent 的典型落地场景与瓶颈",
  "RAG 检索增强生成的主流方案对比",
  "向量索引 HNSW 与 IVF 的取舍"
];

const area = ref<HTMLTextAreaElement | null>(null);

/** 输入框跟着内容长高，避免长主题被截在一个小滚动区里。 */
function autosize(): void {
  const el = area.value;
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
}

function useExample(text: string): void {
  props.store.topic = text;
  void nextTick(autosize);
}

function onKeydown(event: KeyboardEvent): void {
  // Enter 直接开跑，Shift+Enter 换行 —— 和搜索框的习惯一致
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    void props.store.start();
  }
}

onMounted(autosize);
watch(() => props.store.topic, () => void nextTick(autosize));
</script>

<template>
  <section class="card query">
    <header class="card-head">
      <span class="card-title">研究主题</span>
      <span class="hint">Enter 开始 · Shift + Enter 换行</span>
    </header>

    <div class="card-body">
      <textarea
        ref="area"
        v-model="store.topic"
        class="input"
        rows="2"
        placeholder="想研究点什么？例如：边缘计算在工业质检中的落地现状"
        :disabled="store.busy"
        @keydown="onKeydown"
      ></textarea>

      <div class="examples">
        <button
          v-for="example in EXAMPLES"
          :key="example"
          type="button"
          class="chip"
          :disabled="store.busy"
          @click="useExample(example)"
        >
          {{ example }}
        </button>
      </div>

      <div class="actions">
        <div class="buttons">
          <button
            v-if="!store.busy"
            type="button"
            class="btn btn-primary"
            :disabled="!store.topic.trim()"
            @click="store.start()"
          >
            开始研究
          </button>
          <button v-else type="button" class="btn" @click="store.stop()">停止</button>
          <button
            v-if="store.phase !== 'idle' && !store.busy"
            type="button"
            class="btn btn-ghost"
            @click="store.reset()"
          >
            清空
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.query :deep(.card-body) {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.hint {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-mute);
}

.input {
  width: 100%;
  min-height: 78px;
  padding: 12px 14px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text);
  font-size: 15px;
  line-height: 1.6;
  resize: none;
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}

.input::placeholder {
  color: var(--text-mute);
}

.input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.examples {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.chip {
  padding: 4px 11px;
  border: 1px dashed var(--border-strong);
  border-radius: 999px;
  background: transparent;
  color: var(--text-dim);
  font-size: 12.5px;
  cursor: pointer;
  transition: color var(--dur) var(--ease), border-color var(--dur) var(--ease),
    background var(--dur) var(--ease);
}

.chip:hover:not(:disabled) {
  color: var(--accent);
  border-color: var(--accent-line);
  border-style: solid;
  background: var(--accent-soft);
}

.chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 2px;
}

.buttons {
  display: flex;
  gap: 8px;
  margin-left: auto;
}
</style>
