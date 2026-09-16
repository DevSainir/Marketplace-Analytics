<script setup>
/**
 * One figure of «Итог по тесту», and — when more than one campaign paid for it
 * — what each of them contributed.
 *
 * The tile is a tree rather than a row of extra numbers, because the branches
 * are not four more metrics: they are the same metric taken apart, and they add
 * back up to the trunk. A reader who can see that adds the two halves in their
 * head and either believes the total or finds the discrepancy — which is the
 * whole reason the split is shown instead of just used.
 *
 * With a single campaign there is nothing to take apart and the tile renders as
 * the plain figure it always was. That is the ordinary case and it must not
 * grow furniture it has no use for.
 */
import { computed } from 'vue'

import MetricHint from '@/modules/abTests/components/MetricHint.vue'

const props = defineProps({
  /** The metric's label, e.g. «Показов». */
  label: { type: String, required: true },
  /** The whole-test figure, already formatted. */
  value: { type: String, required: true },
  /** The explanation behind the label; omitted for a self-evident one. */
  hint: { type: String, default: '' },
  /** `[{ name, value }]` per campaign — empty when only one paid. */
  branches: { type: Array, default: () => [] },
  /** Which `data-testid` the figure carries, so the page's tests can find it. */
  testid: { type: String, default: '' },
})

const split = computed(() => props.branches.length > 1)

/**
 * Where the horizontal connector starts and stops.
 *
 * It spans centre-to-centre of the outer branches, not edge to edge: a line
 * that ran the full width would point at nothing on either end. Each branch is
 * `100 / n` percent wide, so the first centre is at half of that.
 */
const span = computed(() => `${50 / props.branches.length}%`)
</script>

<template>
  <div :class="split ? 'text-center' : ''">
    <dt
      class="flex items-center gap-xs text-tiny font-medium text-muted"
      :class="split ? 'justify-center' : ''"
    >
      <span>{{ label }}</span>
      <MetricHint v-if="hint" :text="hint" />
    </dt>
    <dd class="mt-xs text-h2 font-bold tabular-nums text-primary" :data-testid="testid || null">
      {{ value }}
    </dd>

    <div v-if="split" class="ab-tile__tree mt-sm" data-testid="tile-branches">
      <div class="ab-tile__fork" :style="{ left: span, right: span }"></div>
      <div class="ab-tile__branches">
        <div v-for="branch in branches" :key="branch.name" class="ab-tile__branch px-xs">
          <p class="text-base font-semibold tabular-nums text-primary">{{ branch.value }}</p>
          <p class="ab-tile__branch-name text-micro text-muted" :title="branch.name">
            {{ branch.name }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped src="@/modules/abTests/components/styles/SummaryMetricTile.css"></style>
