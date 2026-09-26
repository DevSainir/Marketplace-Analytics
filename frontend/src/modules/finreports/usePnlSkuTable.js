/**
 * Состояние и форматирование таблицы «По артикулам» — всё, что не разметка.
 *
 * Вынесено из `PnlSkuDataTable.vue` по той же причине, по которой из него уже
 * вынесены карточки: два десятка определений колонок и так занимают файл
 * целиком, и любая логика рядом с ними перестаёт читаться. Здесь — какие
 * артикулы раскрыты и как выглядит строка «Итого»; там — только колонки.
 */
import { computed, ref, watch } from 'vue'

import { formatNumber } from '@/core/utils/format'
import { money, pct } from '@/modules/finreports/pnlFormat'

/**
 * Which articles are expanded, in the shape PrimeVue expects (a map by
 * `dataKey`), and asking for each open article's sizes whenever it has none.
 *
 * Asking only on the click was the other half of the endless «Считаем
 * размеры…»: the store drops every article's sizes when the report reloads —
 * a new period, or a «Не включать в общий счёт» toggle — while the rows stay
 * open, so an open row was left with nothing and nothing asking for it. The
 * watch re-asks for exactly those; the store ignores an article already
 * loaded or loading, so it costs nothing otherwise.
 *
 * @param {(nmId: number) => void} onOpen Asks for one article's sizes.
 * @param {() => object} sizesOf The store's nm_id -> state map.
 */
export function useExpandedSkus(onOpen, sizesOf = () => ({})) {
  const expanded = ref({})

  function toggle(nmId) {
    if (expanded.value[nmId]) {
      const rest = { ...expanded.value }
      delete rest[nmId]
      expanded.value = rest
      return
    }
    expanded.value = { ...expanded.value, [nmId]: true }
    onOpen(nmId)
  }

  watch([expanded, sizesOf], ([open, sizes]) => {
    for (const nmId of Object.keys(open)) {
      if (!sizes[nmId]) onOpen(Number(nmId))
    }
  })

  return { expanded, toggle }
}

/**
 * Готовые ячейки строки «Итого». Собраны заранее, чтобы каждая колонка несла
 * один `:footer`, а не блок форматирования внутри шаблона.
 *
 * @param {import('vue').Ref<object|null>} totals Строка из `sumRows`.
 */
export function useFooterCells(totals) {
  return computed(() => {
    const t = totals.value
    if (!t) return {}
    const drr = t.advertisingPct === null ? '' : ` (${pct(t.advertisingPct)})`
    return {
      saName: t.excludedCount ? `Итого (без ${t.excludedCount})` : 'Итого',
      orders: t.orders === null ? '' : formatNumber(t.orders),
      sold: formatNumber(t.sold),
      returnPct: pct(t.returnPct),
      sales: money(t.sales),
      averageCheque: money(t.averageCheque),
      sppPct: pct(t.sppPct),
      logistics: `${money(t.logistics)} (${pct(t.logisticsPct)})`,
      penalties: money(t.penalties),
      cogs: money(t.cogs),
      advertising: `${money(t.advertising)}${drr}`,
      adBonus: t.adBonus ? `−${money(t.adBonus)}` : money(t.adBonus),
      roi: pct(t.roi),
      romi: pct(t.romi),
      payout: money(t.payout),
    }
  })
}
