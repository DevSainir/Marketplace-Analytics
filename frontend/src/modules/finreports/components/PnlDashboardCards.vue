<script setup>
/**
 * The P&L dashboard — five KPI cards over the selected period.
 *
 * Reads the backend-computed, exclusion-aware `dashboard` object (not `totals`):
 * the four per-SKU cards drop the SKUs the seller marked «Не включать в общий
 * счёт», while «Прочие удержания» is account-level money with no SKU and so is
 * never affected by a mark. All the arithmetic is the backend's — this only
 * formats it.
 *
 * - «Продажи» — revenue NET of returns at the page's price base (`priceBase.js`),
 *   which the card names, then the units bought out and returned. Units are
 *   net too: a gross unit count over a net figure, while part of those units
 *   came back, made the money and the count disagree.
 * - «Логистика» — the full delivery bill and its share of sales at the same
 *   base.
 * - «Прочие удержания» — WB's own «Прочие удержания» line (Σ deduction), with
 *   the advertising («ВБ.Продвижение») share it is mostly made of.
 * - «Себестоимость» — the seller's own cost of the sold units; flags how many
 *   SKUs still have no cost, because the profit is understated by exactly them,
 *   and says «Заполнить →» / «Изменить →» — it is the way into the cost editor.
 *   With gaps it is two actions, not one link: «Показать их» narrows the table
 *   below to exactly those SKUs (`show-uncosted`), where each can be costed in
 *   place, and «Заполнить →» still opens the editor for the Excel route.
 * - «Итого к оплате» — what actually reaches the bank account after every
 *   withholding, minus any marked SKUs (WB's own name for this total).
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import KpiTile from '@/core/components/KpiTile.vue'
import { formatMoney, formatNumber, formatPercent } from '@/core/utils/format'
import { PRICE_BASES, atBase, shareOf, usePriceBase } from '@/modules/finreports/priceBase'

const props = defineProps({
  /** @type {object} The report's exclusion-aware `dashboard` object. */
  dashboard: { type: Object, required: true },
  currency: { type: String, default: '' },
})

const emit = defineEmits(['show-uncosted'])

const COST_EDITOR = { name: 'finreports-cost-prices' }

const base = usePriceBase()

const money = (value) => formatMoney(value, props.currency)
const pct = formatPercent

const cards = computed(() => {
  const d = props.dashboard
  const excluded = Number(d.excluded_count) || 0
  const sales = atBase(base(), d.sales, d.paid)
  const returned = Number(d.returned_units) || 0
  const logisticsShare = `${pct(shareOf(d.logistics, sales))} от продаж`
  return [
    {
      key: 'sales',
      label: 'Продажи',
      value: money(sales),
      caption: PRICE_BASES.find((b) => b.key === base())?.caption ?? '',
      sub: `${formatNumber(Number(d.sold_units) - returned)} шт · возвраты ${formatNumber(returned)} шт`,
      hint: 'Продажи минус возвраты. Возврат — товар, который вернули после покупки, а не отменённый заказ.',
      to: null,
    },
    {
      key: 'logistics',
      label: 'Логистика',
      value: money(d.logistics),
      sub: logisticsShare,
      to: null,
    },
    {
      key: 'other',
      label: 'Прочие удержания',
      value: money(d.other_deductions),
      sub: d.filtered
        ? `в т.ч. реклама: ${money(d.advertising)} · на весь счёт`
        : `в т.ч. реклама: ${money(d.advertising)}`,
      hint: 'WB списывает их со всего кабинета, а не с артикулов. Поэтому фильтры эту карточку не меняют.',
      to: null,
    },
    {
      key: 'cogs',
      label: 'Себестоимость',
      value: money(d.cogs),
      sub: d.uncosted_count > 0 ? `без себестоимости: ${d.uncosted_count} SKU` : 'все SKU покрыты',
      // The editor's only entrance since «Себестоимость» left the page header.
      // With gaps the tile carries two actions (below), so it is not a link.
      to: d.uncosted_count > 0 ? null : COST_EDITOR,
      action: d.uncosted_count > 0 ? '' : 'Изменить →',
      gaps: d.uncosted_count > 0,
      warn: d.uncosted_count > 0,
    },
    {
      key: 'payout',
      label: 'Итого к оплате',
      value: money(d.payout_net),
      sub:
        excluded > 0 ? `на счёт · исключено ${excluded} SKU` : 'на счёт, после всех удержаний WB',
      to: null,
      accent: true,
    },
  ]
})
</script>

<template>
  <!-- Two-up wraps «2 403 199 KGS» onto a second line at 402pt and leaves the
       fifth card alone on its own row; one column keeps each figure whole. -->
  <section
    class="grid grid-cols-2 gap-md phone:grid-cols-1 phone:gap-sm md:grid-cols-3 xl:grid-cols-5"
  >
    <KpiTile
      v-for="card in cards"
      :key="card.key"
      :label="card.label"
      :value="card.value"
      :caption="card.caption ?? ''"
      :sub="card.sub ?? ''"
      :sub-warn="Boolean(card.warn)"
      :tone="card.accent ? 'accent' : 'default'"
      :hint="card.hint ?? ''"
      :to="card.to ?? null"
      :action="card.action ?? ''"
    >
      <div v-if="card.gaps" class="mt-sm flex flex-wrap gap-x-md gap-y-xs text-tiny font-medium">
        <button
          type="button"
          class="text-action hover:underline"
          data-testid="show-uncosted"
          @click="emit('show-uncosted')"
        >
          Показать их ↓
        </button>
        <RouterLink :to="COST_EDITOR" class="text-action hover:underline">Заполнить →</RouterLink>
      </div>
    </KpiTile>
  </section>
</template>
