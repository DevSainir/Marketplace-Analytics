<script setup>
/**
 * «Открутка по дням» on the kit's own chart — money only, one scale.
 *
 * The live page draws ДРР as a dashed line on a second, percent axis. The kit
 * has one axis by design, and two scales on one plot invite reading their
 * crossings as meaningful, so ДРР moved into the hover tooltip, under the
 * day's money (`tipNote`). The days past the settlement — no sales yet, so no
 * ДРР — are a shaded band rather than a line that stops without saying why.
 *
 * With bonuses shown the day is two stacked layers that add up to its whole
 * spend: the seller's own money in `--fact`, WB's bonus above it in
 * `--brand-2`, the lighter step of the same colour — it is the same spend, paid
 * by someone else. With them hidden it is one `--fact` area.
 */
import { computed } from 'vue'

import { dateRu, ratioPct, shortMoney } from '@/modules/labs/advertising/adsFormat'
import BcChart from '@/modules/labs/advertising/components/BcChart.vue'
import { drrOf } from '@/modules/labs/advertising/skuModel'

const props = defineProps({
  /** API `days`. */
  days: { type: Array, required: true },
  currency: { type: String, default: '' },
  showBonus: { type: Boolean, default: false },
  /** False when spend and sales are in different currencies — no ДРР then. */
  showDrr: { type: Boolean, default: true },
})

const money = (value) => shortMoney(value, props.currency)
const spend = computed(() => props.days.map((d) => Number(d.spend)))
const bonus = computed(() => props.days.map((d) => Number(d.bonus)))
const own = computed(() => spend.value.map((v, i) => v - bonus.value[i]))

/** Per-day ДРР from the seller's own money; `null` past the settlement. */
const drr = computed(() =>
  props.days.map((d, i) => (d.sales === null ? null : drrOf(own.value[i], Number(d.sales)))),
)

/** First day with no settled sales, when the window runs past the settlement. */
const unsettledFrom = computed(() => {
  const i = props.days.findIndex((d) => d.sales === null)
  return i > 0 ? i : -1
})

function note(i) {
  if (!props.showDrr) return ''
  const text =
    props.days[i].sales === null ? 'продажи ещё не рассчитаны' : `ДРР ${ratioPct(drr.value[i])}`
  return `<div class="tn">${text}</div>`
}

const series = computed(() =>
  props.showBonus
    ? [
        {
          name: 'Промо-бонусы',
          values: spend.value,
          base: own.value,
          color: 'var(--brand-2)',
          tip: bonus.value.map(money),
        },
        {
          name: 'С баланса',
          values: own.value,
          base: own.value.map(() => 0),
          color: 'var(--fact)',
        },
      ]
    : [{ name: 'Расход', values: spend.value, color: 'var(--fact)', area: true }],
)

const options = computed(() => ({
  days: props.days.length,
  labels: props.days.map((d) => `${d.day.slice(8, 10)}.${d.day.slice(5, 7)}`),
  H: 260,
  valueFmt: money,
  tipHead: (i) => dateRu(props.days[i].day),
  tipNote: note,
  series: series.value,
  bands:
    props.showDrr && unsettledFrom.value > 0
      ? [{ a: unsettledFrom.value, b: props.days.length - 1, cls: 'ly', label: 'без продаж' }]
      : [],
}))

const lead = computed(() => {
  const peak = spend.value.indexOf(Math.max(...spend.value))
  const mean = spend.value.reduce((sum, v) => sum + v, 0) / spend.value.length
  return (
    `В среднем ${money(mean)} в день, больше всего — ${dateRu(props.days[peak].day)}: ` +
    `${money(spend.value[peak])}.`
  )
})
</script>

<template>
  <section class="band band--surface">
    <div class="app-container stack">
      <h2 class="t-display">Открутка по дням</h2>
      <p class="lead">{{ lead }}</p>
      <div class="legend">
        <template v-if="showBonus">
          <span><i class="sq" style="background: var(--fact)" />С баланса</span>
          <span><i class="sq" style="background: var(--brand-2)" />Промо-бонусы</span>
        </template>
        <span v-else><i style="border-color: var(--fact)" />Расход</span>
        <span v-if="showDrr">ДРР по дням — при наведении</span>
      </div>
      <BcChart :options="options" />
    </div>
  </section>
</template>
