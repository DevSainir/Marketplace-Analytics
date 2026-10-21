<script setup>
/**
 * The card with an article's penalty reasons — opened from «N причин» next to
 * the amount.
 *
 * The reasons used to sit as lines inside the cell itself, and the article's
 * row grew by five or six lines of text: «Штраф МП. Невыполненный заказ
 * (отправка товара отличного от заявленного)» does not abbreviate. Now the row
 * is always one line high and the reasons live here. On click, not on hover:
 * the text is long, people read it, and the hand should not have to hold the
 * cursor still.
 *
 * One per table and owned by it, not by the cell: PrimeVue re-renders the cell
 * on a row click, and a card inside it closed the moment it opened. Teleported
 * to `<body>` and kept inside the visible part of the table
 * (`core/utils/tipFit`). Closes on an outside click, Esc and scroll — it is
 * `fixed` and would otherwise stay hanging over someone else's row.
 */
import { onBeforeUnmount, watch } from 'vue'

import { vFitInside } from '@/core/utils/tipFit'

const props = defineProps({
  /** @type {{key: unknown, reasons: Array<{reason: string, amount: string}>, top: number, left: number, area: object}|null} */
  open: { type: Object, default: null },
})

const emit = defineEmits(['close'])

const close = () => emit('close')

/** A click outside the card. Not on «N причин» itself: its own click decides. */
function onOutside(event) {
  if (!event.target.closest?.('.pnl-penalty-card, .pnl-penalty-more')) close()
}

function onKey(event) {
  if (event.key === 'Escape') close()
}

function listen(on) {
  const method = on ? 'addEventListener' : 'removeEventListener'
  document[method]('pointerdown', onOutside, true)
  document[method]('keydown', onKey, true)
  document[method]('scroll', close, true)
}

watch(
  () => !!props.open,
  (isOpen) => listen(isOpen),
)
onBeforeUnmount(() => listen(false))
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      v-fit-inside="open.area"
      class="pnl-penalty-card fixed z-50 w-96 rounded-card border border-border-subtle bg-surface p-sm text-left shadow-card"
      role="dialog"
      aria-label="Причины штрафов"
      :style="{ top: `${open.top}px`, left: `${open.left}px` }"
    >
      <p class="mb-xs text-tiny font-medium text-muted">Причины штрафов</p>
      <ul class="max-h-64 space-y-xs overflow-y-auto">
        <li
          v-for="p in open.reasons"
          :key="p.reason"
          class="flex items-baseline justify-between gap-md text-tiny text-primary"
        >
          <span>{{ p.reason }}</span>
          <span class="flex-none font-medium tabular-nums">{{ p.amount }}</span>
        </li>
      </ul>
    </div>
  </Teleport>
</template>
