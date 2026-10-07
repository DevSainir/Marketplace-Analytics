<script setup>
/**
 * What a block shows in place of its figures: loading, nothing, or a failure.
 *
 * One look for all three, on every page. Before this, «loading» was a card on
 * the P&L, a bare line on the heatmap and nothing at all on the A/B list; an
 * error was red text on one page, a pink plate on another and a GREY card on a
 * third; and the words ran to a dozen variants («Загрузка…», «Загружаю
 * данные…», «Считаем отчёт…»). Pages now pick a `kind` and, at most, their own
 * wording for an empty block.
 *
 * `layout`:
 * - `card` — the block's own card, standing where the block will be;
 * - `bare` — the same content without the card, for a place already inside one
 *   (a table body, a section card);
 * - `line` — a one-line failure ABOVE figures that stay on screen: a failed
 *   reload or save must not take away what was already there. No heading —
 *   the same line reports a failed reload and a failed save, and the reason
 *   (`extractErrorMessage`) already says which.
 */
import { computed } from 'vue'

import BusyBar from '@/core/components/BusyBar.vue'

const props = defineProps({
  /** `'loading'`, `'empty'` or `'error'`. */
  kind: { type: String, required: true },
  /** For `error` the reason (already Russian — `extractErrorMessage`); for `empty` the line itself. */
  text: { type: String, default: '' },
  /** A second, smaller line under an empty block: what to do about it. */
  hint: { type: String, default: '' },
  layout: { type: String, default: 'card' },
})

const EMPTY = 'Нет данных за выбранный период'
const FAILED = 'Не удалось загрузить'

const frame = computed(() => {
  if (props.layout === 'bare') return 'px-md py-xl text-center'
  const tone =
    props.kind === 'error'
      ? 'border-status-negative/30 bg-status-negative/10'
      : 'border-border-subtle bg-surface shadow-card'
  return `rounded-card border px-lg py-xl text-center ${tone}`
})
</script>

<template>
  <p
    v-if="layout === 'line'"
    class="rounded-input border border-status-negative/30 bg-status-negative/10 px-md py-sm text-base text-status-negative"
    role="alert"
  >
    {{ text }}
  </p>

  <div v-else :class="frame">
    <BusyBar v-if="kind === 'loading'" label="Загружаем…" />

    <div v-else-if="kind === 'error'" role="alert">
      <p class="font-semibold text-status-negative">{{ FAILED }}</p>
      <p v-if="text" class="mt-xs text-base text-primary">{{ text }}</p>
    </div>

    <template v-else>
      <p class="text-base text-muted">{{ text || EMPTY }}</p>
      <p v-if="hint" class="mt-xs text-tiny text-muted">{{ hint }}</p>
    </template>
  </div>
</template>
