<script setup>
/**
 * Карточка с причинами штрафов артикула — открывается по «N причин» у суммы.
 *
 * Причины раньше стояли строками в самой ячейке, и строка артикула вырастала
 * на пять-шесть строк текста: «Штраф МП. Невыполненный заказ (отправка товара
 * отличного от заявленного)» не сокращается. Теперь строка всегда одной
 * высоты, а причины — здесь. По клику, а не по наведению: текст длинный, его
 * читают, и рука не должна держать курсор на месте.
 *
 * Одна на таблицу и живёт в ней, а не в ячейке: PrimeVue перерисовывает ячейку
 * на клик по строке, и карточка внутри неё закрывалась, едва открывшись.
 * Вынесена в `<body>` и держится внутри видимой части таблицы
 * (`core/utils/tipFit`). Закрывается кликом мимо, Esc и прокруткой — она
 * `fixed` и иначе осталась бы висеть над чужой строкой.
 */
import { onBeforeUnmount, watch } from 'vue'

import { vFitInside } from '@/core/utils/tipFit'

const props = defineProps({
  /** @type {{key: unknown, reasons: Array<{reason: string, amount: string}>, top: number, left: number, area: object}|null} */
  open: { type: Object, default: null },
})

const emit = defineEmits(['close'])

const close = () => emit('close')

/** Клик мимо карточки. По самой «N причин» — нет: её клик решает сам. */
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
