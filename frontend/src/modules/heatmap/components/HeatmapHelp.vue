<script setup>
/**
 * "How to use" — the page's own short manual, opened in place.
 *
 * Deliberately short: what the colours mean, the two ways of comparing, the
 * second metric and the two "Total"s. The method behind the colour lives in
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
      ⓘ How to use
    </button>
    <div v-if="open" class="fixed inset-0 z-30" @click="open = false"></div>
    <div
      v-if="open"
      class="ui-pop ui-glass ui-glass--pop right-0 mt-xs max-h-[70vh] w-[min(28rem,calc(100vw-32px))] overflow-y-auto p-lg text-base text-primary"
    >
      <p>
        <b>Color.</b> The target is the median. Above it is green, below it red; the closer to the
        best or worst value, the brighter. For ACoS, CPC, CPM, CPO and ad spend, lower is better.
        Prices, WB discount and stock are purple: the higher the value, the brighter. "Total" and
        empty cells are not colored.
      </p>
      <p class="mt-sm">
        <b>By row.</b> Figures are compared within one row (an SKU, brand, category or group) over
        the selected period. The target is computed for that row alone.
      </p>
      <p class="mt-sm">
        Useful for reading one item's own trend: where it grows, where it dips, where it wavers.
      </p>
      <p class="mt-sm">
        <b>Whole table.</b> Figures are compared across every row of the current selection. The
        target is computed over the whole table. Useful for ranking: finding the leaders, the
        laggards and the overall level.
      </p>
      <p class="mt-sm">
        <b>Target.</b> "Median" — computed for you. "Manual" — type your own target for an SKU in
        the "Target" column, and the color shows whether it is above or below. A target is per day;
        the weekly and monthly views multiply it by the number of days (except percentages, prices
        and stock). Each metric has its own target. Works only with rows by SKU. With "Whole table"
        an SKU is still compared with its own target, but the brightest color goes to the largest
        deviation in the table, so small SKUs look paler.
      </p>
      <p class="mt-sm">
        <b>Two metrics.</b> Pick a second one on the right: each cell then holds two numbers, the
        primary on top (it sets the color) and the second below. ⇄ swaps them.
      </p>
      <p class="mt-sm">
        <b>Total.</b> The top row: every selected SKU, per column. The left column: each row over
        the whole period.
      </p>
    </div>
  </div>
</template>
