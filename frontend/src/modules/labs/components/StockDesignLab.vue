<script setup>
import StockCardsTable from '@/modules/labs/components/StockCardsTable.vue'
import StockHeatTable from '@/modules/labs/components/StockHeatTable.vue'
import StockTerminalTable from '@/modules/labs/components/StockTerminalTable.vue'

/**
 * LAB-ONLY: three candidate redesigns of «Остатки по складам», stacked under
 * the current grid so the four can be compared on the same data.
 *
 * All three keep the grid's two hard rules — it scrolls sideways through the
 * period, and a screen holds exactly two days — and all three sit in the same
 * shell (`StockRibbon.vue`), so what differs between them is only the look.
 * None of them goes to /monitoring as it stands; the one that wins does.
 */
defineProps({
  /** @type {Array<{stat_date: string, stock: ?object}>} oldest day first. */
  days: { type: Array, default: () => [] },
  /** The union of every day's sizes. */
  sizeOrder: { type: Array, default: () => [] },
})

const VARIANTS = [
  {
    id: 'heat',
    name: 'Теплокарта',
    note: 'Цвет плитки — сколько штук лежит. Кучи и дыры видны раньше цифр. Наведи на ячейку: строка и склад останутся, остальное притухнет.',
    component: StockHeatTable,
  },
  {
    id: 'terminal',
    name: 'Терминал',
    note: 'Тёмный биржевой экран. Под каждой цифрой — сколько ушло или пришло за день, изменившиеся ячейки подсвечены.',
    component: StockTerminalTable,
  },
  {
    id: 'cards',
    name: 'Карточки дней',
    note: 'Каждый день — отдельная карточка. У склада свой цвет на весь период, полоска в шапке — как остаток разложен по складам.',
    component: StockCardsTable,
  },
]
</script>

<template>
  <section
    class="mt-2xl border-t border-border-subtle pt-lg"
    aria-label="Остатки: варианты дизайна"
  >
    <h2 class="text-h2 font-semibold text-primary">Остатки — три новых дизайна</h2>
    <p class="mt-xs max-w-3xl text-base text-muted">
      Те же данные, что в таблице выше. Везде два дня на экране и прокрутка вбок — колесом,
      перетаскиванием, стрелками или точками. Отпустил — лента сама встаёт ровно на границу дня.
    </p>

    <div v-for="(variant, i) in VARIANTS" :key="variant.id" class="mt-xl">
      <div class="mb-sm flex items-baseline gap-sm">
        <span class="text-tiny font-bold uppercase tracking-wider text-action">
          Вариант {{ i + 1 }}
        </span>
        <h3 class="text-h3 font-semibold text-primary">{{ variant.name }}</h3>
      </div>
      <p class="mb-md max-w-3xl text-base text-muted">{{ variant.note }}</p>
      <component :is="variant.component" :days="days" :size-order="sizeOrder" />
    </div>
  </section>
</template>
