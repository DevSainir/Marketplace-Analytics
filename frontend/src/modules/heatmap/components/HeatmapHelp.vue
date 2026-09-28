<script setup>
/**
 * «Как использовать» — the page's own short manual, opened in place.
 *
 * Kept to what the screen cannot say by itself: what the colours mean, the two
 * ways of comparing, how the two «Итого» are counted, and why the finance
 * figures stop a few days short of today.
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
      class="ui-pop right-0 mt-xs w-[min(28rem,calc(100vw-32px))] bg-surface p-lg text-base text-primary shadow-card"
    >
      <p>
        Выберите период и метрику. Каждая строка — артикул (или категория, бренд, группа), каждая
        колонка — день, неделя или месяц.
      </p>
      <p class="mt-sm">
        <b>Цвет.</b> Зелёный — лучше, красный — хуже, бледный — середина. Для ДРР, CPC, CPM, CPO и
        расхода на рекламу лучше — меньше. Цены, СПП и остатки окрашены одним цветом по величине.
      </p>
      <p class="mt-sm">
        <b>Вид.</b> «По строке» — артикул сравнивается со своими же днями: видно, где просел. «По
        всей таблице» — все строки в одной шкале: видно лидеров и отстающих.
      </p>
      <p class="mt-sm">
        <b>Две метрики.</b> Выберите вторую справа — в ячейке будет два числа: сверху основная (по
        ней цвет), снизу вторая. ⇄ меняет их местами.
      </p>
      <p class="mt-sm">
        <b>Итого.</b> Строка сверху — все выбранные артикулы за день. Колонка слева — строка за весь
        период. Проценты считаются от сумм, а не как среднее процентов; остаток — на последний день.
      </p>
      <p class="mt-sm">
        <b>Финансы.</b> Выручка, продажи, прибыль и маржа приходят из отчётов WB раз в неделю,
        поэтому последние дни пустые. Прибыль — выплата минус себестоимость и реклама (без учёта
        бонусов WB); без себестоимости не считается.
      </p>
    </div>
  </div>
</template>
