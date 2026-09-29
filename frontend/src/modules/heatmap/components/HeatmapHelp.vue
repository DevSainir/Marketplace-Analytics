<script setup>
/**
 * «Как использовать» — the page's own short manual, opened in place.
 *
 * Deliberately short: what the colours mean, the two ways of comparing, the
 * second metric and the two «Итого». The method behind the colour lives in
 * `heatScale.js`, not in front of the seller.
 */
import { ref } from 'vue'

const open = ref(false)
</script>

<template>
  <div class="relative">
    <button
      type="button"
      class="text-base font-medium text-action hover:underline"
      :aria-expanded="open"
      @click="open = !open"
    >
      ⓘ Как использовать
    </button>
    <div v-if="open" class="fixed inset-0 z-30" @click="open = false"></div>
    <div
      v-if="open"
      class="ui-pop right-0 mt-xs max-h-[70vh] w-[min(28rem,calc(100vw-32px))] overflow-y-auto bg-surface p-lg text-base text-primary shadow-card"
    >
      <p>
        <b>Цвет.</b> Зелёный — лучше обычного, красный — хуже, белый — обычный день. Для ДРР, CPC,
        CPM, CPO и расхода на рекламу лучше — меньше. Цены, СПП и остатки — фиолетовые: чем ярче,
        тем дальше от обычного. «Итого» и пустые ячейки не красятся.
      </p>
      <p class="mt-sm">
        <b>По строке.</b> Каждая строка — товар, бренд, категория или группа — сравнивается только
        сама с собой за выбранный период: обычный уровень у каждой строки свой. Помогает увидеть,
        как менялся конкретный товар: где рос, где проседал и насколько ровно работал.
      </p>
      <p class="mt-sm">
        <b>По всей таблице.</b> Все строки выборки сравниваются друг с другом на одной шкале:
        обычный уровень общий для всей таблицы. Помогает расставить товары по местам — кто лидирует,
        кто отстаёт и какой уровень типичен для ассортимента.
      </p>
      <p class="mt-sm">
        <b>Две метрики.</b> Выберите вторую справа — в ячейке будет два числа: сверху основная (по
        ней цвет), снизу вторая. ⇄ меняет их местами.
      </p>
      <p class="mt-sm">
        <b>Итого.</b> Строка сверху — все выбранные артикулы за день. Колонка слева — строка за весь
        период.
      </p>
    </div>
  </div>
</template>
