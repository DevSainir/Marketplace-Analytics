/**
 * Шапка и панель управления: период, пресеты, база выручки, сброс допущений.
 */
import { $, panels } from '@/modules/labs/finmodel/dom'
import { addDays, dateRu, esc } from '@/modules/labs/finmodel/format'
import { TABS, render } from '@/modules/labs/finmodel/render'
import { DP, S, defaults, persist } from '@/modules/labs/finmodel/state'

/* ── шапка и управление ─────────────────────────────────────────── */
export function buildChrome() {
  var m = DP.meta
  $('stamp').innerHTML =
    'P&amp;L <b>' +
    dateRu(m.pnl_from) +
    ' — ' +
    dateRu(m.pnl_to) +
    '</b><br>' +
    'Заказы <b>' +
    dateRu(m.orders_from) +
    ' — ' +
    dateRu(m.orders_to) +
    '</b><br>' +
    'Остатки замерены <b>' +
    dateRu(m.stock_asof) +
    '</b> · KGS'

  $('tabs').innerHTML = TABS.map(function (t) {
    return (
      '<button class="tab" role="tab" type="button" data-t="' +
      t.id +
      '" aria-selected="' +
      (t.id === S.tab) +
      '">' +
      esc(t.name) +
      '</button>'
    )
  }).join('')
  $('tabs').addEventListener('click', function (ev) {
    var b = ev.target.closest('.tab')
    if (!b) return
    S.tab = b.dataset.t
    panels().forEach(function (p) {
      p.hidden = p.id !== 'p-' + S.tab
    })
    $('tabs')
      .querySelectorAll('.tab')
      .forEach(function (x) {
        x.setAttribute('aria-selected', x.dataset.t === S.tab ? 'true' : 'false')
      })
  })

  var presets = [
    { n: 'Всё окно', from: m.pnl_from, to: m.pnl_to },
    { n: '30 дней', from: addDays(m.pnl_to, -29), to: m.pnl_to },
    { n: '14 дней', from: addDays(m.pnl_to, -13), to: m.pnl_to },
    { n: 'Неделя', from: addDays(m.pnl_to, -6), to: m.pnl_to },
  ]
  $('presets').innerHTML = presets
    .map(function (p, i) {
      return (
        '<button class="chip" type="button" data-i="' +
        i +
        '" aria-pressed="' +
        (p.from === S.from && p.to === S.to) +
        '">' +
        p.n +
        '</button>'
      )
    })
    .join('')
  $('presets').addEventListener('click', function (ev) {
    var b = ev.target.closest('.chip')
    if (!b) return
    var p = presets[+b.dataset.i]
    S.from = p.from
    S.to = p.to
    syncDates(presets)
    render()
  })

  $('dFrom').min = m.pnl_from
  $('dFrom').max = m.orders_to
  $('dTo').min = m.pnl_from
  $('dTo').max = m.orders_to
  function onDate() {
    var a = $('dFrom').value,
      b = $('dTo').value
    if (!a || !b) return
    if (a > b) {
      var t = a
      a = b
      b = t
    }
    S.from = a
    S.to = b
    syncDates(presets)
    render()
  }
  $('dFrom').addEventListener('change', onDate)
  $('dTo').addEventListener('change', onDate)
  syncDates(presets)

  $('revBase').value = S.revBase
  $('revBase').addEventListener('change', function () {
    S.revBase = this.value
    persist()
    render()
  })

  $('reset').addEventListener('click', function () {
    var d = defaults()
    S.growth = {}
    S.buyout = {}
    S.fixed = d.fixed
    S.scenario = d.scenario
    S.horizon = d.horizon
    S.adMult = d.adMult
    S.limitByStock = d.limitByStock
    S.revBase = d.revBase
    S.pinned = []
    S.season = d.season
    S.parBy = d.parBy
    S.parGroup = d.parGroup
    $('revBase').value = S.revBase
    persist()
    render()
  })
  $('controls').hidden = false
  $('tabs').hidden = false
}
function syncDates(presets) {
  $('dFrom').value = S.from
  $('dTo').value = S.to
  $('presets')
    .querySelectorAll('.chip')
    .forEach(function (b) {
      var p = presets[+b.dataset.i]
      b.setAttribute('aria-pressed', p.from === S.from && p.to === S.to ? 'true' : 'false')
    })
}
