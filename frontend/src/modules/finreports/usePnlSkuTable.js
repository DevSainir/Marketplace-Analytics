/**
 * Состояние и форматирование таблицы «По артикулам» — всё, что не разметка.
 *
 * Вынесено из `PnlSkuDataTable.vue` по той же причине, по которой из него уже
 * вынесены карточки: два десятка определений колонок и так занимают файл
 * целиком, и любая логика рядом с ними перестаёт читаться. Здесь — какие
 * артикулы раскрыты и как выглядит строка «Итого»; там — только колонки.
 */
import { computed, ref } from 'vue'

import { formatMoney, formatNumber, formatPercent } from '@/core/utils/format'

/** «—» вместо пустоты: на отчёте пропуск и ноль читаются по-разному. */
export const money = (value) =>
  value === null || value === undefined ? '—' : formatMoney(value, '')
export const pct = (value) => (value === null || value === undefined ? '—' : formatPercent(value))

/**
 * Какие артикулы раскрыты, в том виде, в каком это ждёт PrimeVue (карта по
 * `dataKey`). Загрузка — не наше дело: клик только называет артикул, ответ
 * приходит снаружи, поэтому повторное раскрытие ничего не стоит.
 *
 * @param {(nmId: number) => void} onOpen Вызывается, когда артикул раскрывают.
 */
export function useExpandedSkus(onOpen) {
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
