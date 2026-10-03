<script setup>
/**
 * The block's three caveats — where its figures disagree, and why.
 *
 * They describe how WB settles advertising (reporting periods with holes in
 * them, deductions that exceed the measured spend, bonus money mixed into the
 * deductions), so they are stated next to the numbers rather than in a help
 * page nobody opens. The first two are properties of the whole spend file;
 * the third is about the chosen window.
 */
import { computed } from 'vue'

import { formatMoney, formatNumber } from '@/core/utils/format'

const props = defineProps({
  /** `reconciliation` of the spend file. */
  notes: { type: Object, required: true },
  /** `spendWindow` for the period — the promo note's figures. */
  spend: { type: Object, required: true },
  currency: { type: String, default: '' },
})

const money = (value) => formatMoney(value, props.currency)
const dateRu = (iso) => iso.split('-').reverse().join('.')

const gapList = computed(() =>
  props.notes.gaps.map((gap) => `${dateRu(gap.from)} — ${dateRu(gap.to)}`).join(', '),
)
/** «+7,1%» — signed, with the Russian decimal comma. */
const residualPct = computed(
  () => (props.notes.residualPct > 0 ? '+' : '') + formatNumber(props.notes.residualPct) + '%',
)

const note = 'border-l-2 py-xs pl-md text-tiny leading-relaxed text-muted'
</script>

<template>
  <div class="grid gap-md md:grid-cols-2">
    <p v-if="notes.gaps.length" :class="[note, 'border-status-warning']">
      <b class="font-semibold text-primary">Отчётные периоды идут не встык.</b>
      {{ gapList }} не покрыты ни одним отчётом, а открутка за эти дни —
      {{ money(notes.gapSpent) }} — сидит в следующем удержании. Модель растягивает окно разнесения
      на эти дни, иначе недельная трата схлопывалась бы в два дня и выбивала маржу в минус.
    </p>
    <p :class="[note, 'border-border-strong/25']">
      <b class="font-semibold text-primary">
        Удержано на {{ money(notes.residual) }} больше, чем откручено ({{ residualPct }}).
      </b>
      Часть объясняется хвостом: до начала первого отчётного периода откручено
      {{ money(notes.beforeWindow) }}, и первое удержание частично забирает его.
      <template v-if="notes.noArticle">
        Ещё {{ money(notes.noArticle) }} приходится на кампании без артикула в названии — они
        разносятся по общей доле.
      </template>
      Остаток стоит уточнить в поддержке WB.
    </p>
    <p :class="[note, 'border-border-strong/25 md:col-span-2']">
      <b class="font-semibold text-primary">Промо-бонусы — это не ваши деньги.</b>
      {{ money(spend.promo) }} из {{ money(spend.total) }} открутки за период оплачено бонусами WB.
      В удержания они попадают наравне с балансом, поэтому в марже учтены, но при оценке собственных
      вложений в рекламу эту сумму надо держать отдельно.
    </p>
  </div>
</template>
