<script setup lang="ts">
import { computed } from "vue";
import type { ResearchStore } from "@/composables/useResearch";
import { formatDuration } from "@/utils/format";

const props = defineProps<{ store: ResearchStore }>();

const steps = computed(() =>
  props.store.stages.map((stage, index) => {
    const finished = props.store.phase === "done" || index < props.store.stageIndex;
    const active = !finished && index === props.store.stageIndex && props.store.busy;
    return { ...stage, index, finished, active };
  })
);
</script>

<template>
  <section class="card rail">
    <div class="head">
      <span class="card-title">流程</span>
      <span class="timer">
        <template v-if="store.phase !== 'idle'">{{ formatDuration(store.elapsedMs) }}</template>
        <template v-else>—</template>
      </span>
    </div>

    <div class="bar" role="progressbar" :aria-valuenow="store.progress" aria-valuemin="0" aria-valuemax="100">
      <div
        class="fill"
        :class="{ live: store.busy }"
        :style="{ width: `${store.progress}%` }"
      ></div>
    </div>

    <ol class="steps">
      <li
        v-for="step in steps"
        :key="step.key"
        class="step"
        :class="{ done: step.finished, active: step.active }"
      >
        <span class="marker">
          <svg v-if="step.finished" viewBox="0 0 16 16" width="11" height="11" aria-hidden="true">
            <path
              d="M3 8.5l3.2 3.2L13 5"
              fill="none"
              stroke="currentColor"
              stroke-width="2.2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          <template v-else>{{ step.index + 1 }}</template>
        </span>
        <span class="text">
          <strong>{{ step.label }}</strong>
          <em>{{ step.hint }}</em>
        </span>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.rail {
  padding: 16px 18px 14px;
}

.head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 10px;
}

.timer {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
}

.bar {
  height: 6px;
  border-radius: 999px;
  background: var(--surface-3);
  overflow: hidden;
  margin-bottom: 16px;
}

.fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--accent), var(--accent-2));
  transition: width 480ms var(--ease);
}

.fill.live {
  background-image: linear-gradient(
    100deg,
    var(--accent) 0%,
    var(--accent-2) 40%,
    rgba(255, 255, 255, 0.55) 50%,
    var(--accent-2) 60%,
    var(--accent) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 2.4s linear infinite;
}

.steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.step {
  display: flex;
  gap: 9px;
  align-items: flex-start;
  opacity: 0.5;
  transition: opacity var(--dur) var(--ease);
}

.step.done,
.step.active {
  opacity: 1;
}

.marker {
  flex: none;
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  margin-top: 1px;
  border-radius: 50%;
  border: 1.5px solid var(--border-strong);
  color: var(--text-mute);
  font-size: 11.5px;
  font-weight: 700;
  transition: all var(--dur) var(--ease);
}

.step.done .marker {
  border-color: transparent;
  background: var(--ok-soft);
  color: var(--ok);
}

.step.active .marker {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
  animation: pulse-ring 1.8s var(--ease) infinite;
}

.text {
  display: flex;
  flex-direction: column;
  line-height: 1.35;
  min-width: 0;
}

.text strong {
  font-size: 13.5px;
  font-weight: 600;
}

.text em {
  font-size: 11.5px;
  font-style: normal;
  color: var(--text-mute);
}

@media (max-width: 620px) {
  .steps {
    grid-template-columns: 1fr;
    gap: 8px;
  }
}
</style>
