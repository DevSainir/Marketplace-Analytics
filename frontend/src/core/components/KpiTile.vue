<script setup>
/**
 * One headline figure in a card: a label, the figure, and a line or two of
 * context under it. The P&L's recipe, now everyone's.
 *
 * Five pages drew these five ways — a 21px figure at weight 500 on the
 * summary, semibold on logistics, a micro label and tighter padding in
 * advertising, a hint in a `title` on one and a glass ⓘ on another. What a
 * page says on its tiles is its own; how a tile looks is this file's.
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import InfoHint from '@/core/components/InfoHint.vue'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: String, required: true },
  /** A small line between the figure and the note (the P&L's «из них …»). */
  caption: { type: String, default: '' },
  /** The context line under the figure. */
  sub: { type: String, default: '' },
  /** `default` | `accent` | `positive` | `warning` | `negative` | `muted` — the figure's colour. */
  tone: { type: String, default: 'default' },
  /** The context line in the warning colour. */
  subWarn: { type: Boolean, default: false },
  /** Opens as an ⓘ beside the label. */
  hint: { type: String, default: '' },
  /** A route: the whole tile becomes a link to it. */
  to: { type: [String, Object], default: null },
})

const TONES = {
  default: 'text-primary',
  accent: 'text-action',
  positive: 'text-status-positive',
  warning: 'text-status-warning',
  negative: 'text-status-negative',
  muted: 'text-muted',
}
const toneClass = computed(() => TONES[props.tone] ?? TONES.default)
</script>

<template>
  <component
    :is="to ? RouterLink : 'div'"
    :to="to ?? undefined"
    class="rounded-card border border-border-subtle bg-surface p-lg shadow-card phone:p-md"
    :class="to ? 'transition hover:border-action' : ''"
  >
    <div class="flex items-center text-tiny font-medium uppercase tracking-wide text-muted">
      {{ label }}<InfoHint v-if="hint" :text="hint" />
    </div>
    <div class="mt-xs text-h2 font-bold tabular-nums" :class="toneClass">{{ value }}</div>
    <div v-if="caption" class="mt-xs text-tiny text-muted">{{ caption }}</div>
    <div v-if="sub" class="mt-xs text-tiny" :class="subWarn ? 'text-status-warning' : 'text-muted'">
      {{ sub }}
    </div>
    <slot />
  </component>
</template>
