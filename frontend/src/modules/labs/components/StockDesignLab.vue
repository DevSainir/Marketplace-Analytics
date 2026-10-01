<script setup>
import { reactive } from 'vue'

import StockCurveTable from '@/modules/labs/components/StockCurveTable.vue'
import StockShowcaseTable from '@/modules/labs/components/StockShowcaseTable.vue'
import StockUnitsTable from '@/modules/labs/components/StockUnitsTable.vue'
import { limitWarehouses } from '@/modules/labs/stockRibbonModel'

/**
 * LAB-ONLY: three candidate redesigns of «Остатки по складам», stacked under
 * the current grid so the four can be compared on the same data.
 *
 * Designed for the case the current grid draws worst: ONE to three
 * warehouses. Since 16.08 WB reports a seller's stock as a single
 * «Склад WB», and a grid with a column per warehouse turns that into one
 * column per day stretched across half a screen. All three make the size row
 * the unit instead and the warehouse a colour inside it, so the width is spent
 * on the size curve whatever the warehouse count.
 *
 * All three keep the grid's two hard rules — it scrolls sideways through the
 * period, a screen holds exactly two days — in one shell (`StockRibbon.vue`).
 * Each has its own «Складов (отладка)» knob, opening on ONE warehouse: the
 * case they are for.
 */
defineProps({
  /** @type {Array<{stat_date: string, stock: ?object}>} oldest day first. */
  days: { type: Array, default: () => [] },
  /** The union of every day's sizes. */
  sizeOrder: { type: Array, default: () => [] },
})

const VARIANTS = [
  {
    id: 'curve',
    name: 'Кривая размеров',
    note: 'Каждый день — график размерного ряда. Пунктир — сколько было вчера, красная штриховка — что ушло за день. Шкала общая на весь период: листаешь дни — полки пустеют.',
    component: StockCurveTable,
  },
  {
    id: 'units',
    name: 'Поштучно',
    note: 'Одна точка — одна штука на полке. Пустой красный кружок — штука, которая ушла со вчера, зелёное кольцо — пришла с поставкой. Когда штук станет много, точка начнёт означать 2, 5, 10 шт.',
    component: StockUnitsTable,
  },
  {
    id: 'showcase',
    name: 'Витрина размеров',
    note: 'Как выбор размера в карточке товара: что можно купить сегодня. Штриховка — нет, жёлтый — мало, красная рамка — закончился со вчера. Размер на одном месте в оба дня.',
    component: StockShowcaseTable,
  },
]

/** Per variant: how many warehouses to keep (`null` = all). */
const limits = reactive(Object.fromEntries(VARIANTS.map((v) => [v.id, 1])))

/** Anything that is not a whole number ≥ 1 means «all» — an empty field, a 0. */
function setLimit(id, event) {
  const n = Math.floor(Number(event.target.value))
  limits[id] = event.target.value !== '' && n >= 1 ? n : null
}
</script>

<template>
  <section
    class="mt-2xl border-t border-border-subtle pt-lg"
    aria-label="Остатки: варианты дизайна"
  >
    <h2 class="text-h2 font-semibold text-primary">Остатки — три дизайна под 1–3 склада</h2>
    <p class="mt-xs max-w-3xl text-base text-muted">
      Склад здесь не колонка, а цвет внутри строки размера — один «Склад WB» не оставляет пустых
      полос. Два дня на экране, прокрутка вбок колесом, перетаскиванием, стрелками или точками;
      отпустил — лента встаёт на границу дня. Наведи на размер — он подсветится в обоих днях.
    </p>

    <div v-for="(variant, i) in VARIANTS" :key="variant.id" class="mt-xl">
      <div class="mb-sm flex flex-wrap items-center justify-between gap-sm">
        <div class="flex items-baseline gap-sm">
          <span class="text-tiny font-bold uppercase tracking-wider text-action">
            Вариант {{ i + 1 }}
          </span>
          <h3 class="text-h3 font-semibold text-primary">{{ variant.name }}</h3>
        </div>
        <label class="inline-flex items-center gap-xs text-tiny font-medium text-muted">
          Складов (отладка)
          <input
            type="number"
            min="1"
            step="1"
            inputmode="numeric"
            placeholder="все"
            class="w-16 rounded-btn border border-border-subtle bg-surface px-sm py-xs text-tiny text-primary tabular-nums"
            :value="limits[variant.id] ?? ''"
            @input="setLimit(variant.id, $event)"
          />
        </label>
      </div>
      <p class="mb-md max-w-3xl text-base text-muted">{{ variant.note }}</p>
      <component
        :is="variant.component"
        :days="limitWarehouses(days, limits[variant.id])"
        :size-order="sizeOrder"
      />
    </div>
  </section>
</template>
