/**
 * Список вкладок и полный ререндер страницы.
 */
import { $ } from '@/modules/labs/finmodel/dom'
import { daysBetween } from '@/modules/labs/finmodel/format'
import { fixedPerDay, revOf, slice, sliceSizes } from '@/modules/labs/finmodel/select'
import { DP, S } from '@/modules/labs/finmodel/state'
import { renderAds } from '@/modules/labs/finmodel/tabs/ads'
import { renderFixed } from '@/modules/labs/finmodel/tabs/fixed'
import { renderForecast } from '@/modules/labs/finmodel/tabs/forecast'
import { renderMethod } from '@/modules/labs/finmodel/tabs/method'
import { renderSkus } from '@/modules/labs/finmodel/tabs/skus'
import { renderOos } from '@/modules/labs/finmodel/tabs/stock'
import { renderSummary } from '@/modules/labs/finmodel/tabs/summary'

/* ── вкладки ────────────────────────────────────────────────────── */
export var TABS = [
  { id: 'sum', name: 'Сводка' },
  { id: 'sku', name: 'Артикулы' },
  { id: 'ads', name: 'Реклама' },
  { id: 'oos', name: 'Остатки и аут-оф-сток' },
  { id: 'fc', name: 'Прогноз' },
  { id: 'fix', name: 'Постоянные расходы' },
  { id: 'meth', name: 'Как это считается' },
]

export function render() {
  var from = S.from,
    to = S.to
  var agg = slice(from, to),
    days = daysBetween(from, to)
  var live = DP.skus.filter(function (s) {
    return s.nm_id != null
  })

  var tot = {
    revenue: 0,
    card: 0,
    margin: 0,
    net_units: 0,
    orders: 0,
    cogs: 0,
    logistics: 0,
    ads: 0,
    commission: 0,
    other_wb: 0,
  }
  live.forEach(function (s) {
    var a = agg[s.nm_id]
    if (!a) return
    Object.keys(tot).forEach(function (k) {
      tot[k] += a[k] || 0
    })
  })
  tot.base = revOf(tot)
  var fixedPeriod = fixedPerDay() * days
  var profit = tot.margin - fixedPeriod

  var panels = $('panels')
  panels.innerHTML = TABS.map(function (t) {
    return (
      '<section class="panel" id="p-' +
      t.id +
      '" role="tabpanel"' +
      (t.id === S.tab ? '' : ' hidden') +
      '></section>'
    )
  }).join('')

  renderSummary($('p-sum'), agg, tot, fixedPeriod, profit, days, from, to, live)
  renderSkus($('p-sku'), agg, tot, live, sliceSizes(from, to))
  renderAds($('p-ads'), agg, tot, live, from, to)
  renderOos($('p-oos'), agg, live)
  renderForecast($('p-fc'), agg, live)
  renderFixed($('p-fix'), days, tot)
  renderMethod($('p-meth'))

  $('tabs')
    .querySelectorAll('.tab')
    .forEach(function (b) {
      b.setAttribute('aria-selected', b.dataset.t === S.tab ? 'true' : 'false')
    })
}
