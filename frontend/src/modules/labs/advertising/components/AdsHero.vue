<script setup>
/**
 * The answer — what the period's advertising cost and whether it paid.
 *
 * One figure as large as the kit draws anything (spend), one sentence that
 * says what ДРР means for this seller, and at most three facts under them —
 * the kit's budget for a screen. The band is the brand colour; once ДРР is past
 * the alarm it turns `--hero-hot`, so «плохо» reads from across the room
 * before a single figure is.
 *
 * ДРР is Σ(реклама − бонусы) over settled days ÷ Σ продажи of the same days,
 * never a mean of per-article ratios (see `skuModel.drrOf`).
 *
 * The figures go in through `v-html` because the kit's `BC.bigNum` splits a
 * figure from its units with a `<small>`; it escapes both halves itself.
 */
import { computed } from 'vue'

import { formatMoney } from '@/core/utils/format'
import { DRR_ALARM, bigMoney, dateShort, ratioPct } from '@/modules/labs/advertising/adsFormat'
import { drrOf } from '@/modules/labs/advertising/skuModel'

const props = defineProps({
  totals: { type: Object, required: true },
  currency: { type: String, default: '' },
  showBonus: { type: Boolean, default: false },
  /** False when spend and sales are in different currencies. */
  drrComparable: { type: Boolean, default: true },
  dateFrom: { type: String, required: true },
  dateTo: { type: String, required: true },
})

const spend = computed(() => Number(props.totals.spend))
const bonus = computed(() => Number(props.totals.bonus))

const drr = computed(() => {
  if (!props.drrComparable) return { value: null, why: 'реклама и продажи в разных валютах' }
  if (props.totals.sales === null) return { value: null, why: 'продажи ещё не рассчитаны' }
  if (Number(props.totals.sales) <= 0) return { value: null, why: 'возвратов больше, чем продаж' }
  const own = Number(props.totals.spend_settled) - Number(props.totals.bonus_settled)
  return { value: drrOf(own, Number(props.totals.sales)), why: '' }
})

const hot = computed(() => drr.value.value !== null && drr.value.value > DRR_ALARM)

const verdict = computed(() => {
  if (drr.value.value === null) return `ДРР пока не посчитать: ${drr.value.why}.`
  const tail = hot.value ? 'это выше порога в 20%' : 'это в пределах порога в 20%'
  return `Реклама забрала ${ratioPct(drr.value.value)} от продаж — ${tail}.`
})

const facts = computed(() => [
  ...(props.showBonus
    ? [
        {
          key: 'own',
          label: 'с баланса',
          html: bigMoney(spend.value - bonus.value, props.currency),
        },
        { key: 'bonus', label: 'оплатил WB бонусами', html: bigMoney(bonus.value, props.currency) },
      ]
    : []),
  { key: 'drr', label: 'ДРР от продаж', html: ratioPct(drr.value.value) },
  ...(props.showBonus || props.totals.sales === null
    ? []
    : [
        {
          key: 'sales',
          label: 'продажи за рассчитанные дни',
          html: bigMoney(props.totals.sales, props.currency),
        },
      ]),
])

const period = computed(() => `${dateShort(props.dateFrom)} – ${dateShort(props.dateTo)}`)
const spendLabel = computed(() => formatMoney(spend.value, props.currency))
</script>

<template>
  <section class="band hero" :class="{ 'is-hot': hot }">
    <div class="app-container stack">
      <div class="t-label">Потрачено на рекламу · {{ period }}</div>
      <div class="num-xl" :title="spendLabel" v-html="bigMoney(spend, currency)" />
      <p class="verdict">{{ verdict }}</p>
      <div class="facts">
        <div v-for="fact in facts" :key="fact.key">
          <div class="num-l" v-html="fact.html" />
          <span>{{ fact.label }}</span>
        </div>
      </div>
    </div>
  </section>
</template>
