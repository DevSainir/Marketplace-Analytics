/**
 * Вкладка «Постоянные расходы».
 */
import { dateRu, esc, money, nf2 } from '@/modules/labs/finmodel/format'
import { render } from '@/modules/labs/finmodel/render'
import { baseName, fixedPerDay } from '@/modules/labs/finmodel/select'
import { DAYS_IN_MONTH, S, persist } from '@/modules/labs/finmodel/state'

/* ── Постоянные расходы ─────────────────────────────────────────── */
var FIXED_ROWS = [
  { k: 'taxes', name: 'Налоги', src: 'из выписки' },
  { k: 'insurance', name: 'Страховые взносы', src: 'из выписки' },
  { k: 'bank', name: 'Банковские комиссии', src: 'из выписки' },
  { k: 'salary', name: 'Зарплаты', src: 'в выписке нет — впишите' },
  { k: 'rent', name: 'Аренда', src: 'в выписке нет — впишите' },
  { k: 'other', name: 'Прочее постоянное', src: 'в выписке нет — впишите' },
]

export function renderFixed(el, days, tot) {
  var perDay = fixedPerDay(),
    period = perDay * days
  var h =
    '<div class="stack"><div><div class="sec"><h2>Постоянные расходы</h2>' +
    '<p>Суммы задаются в месяц и пересчитываются на выбранный период по ' +
    nf2.format(DAYS_IN_MONTH) +
    ' дня в месяце. Налоги, взносы и банковские комиссии подставлены ' +
    'из выписки за ' +
    dateRu('2026-07-15') +
    '–' +
    dateRu('2026-09-11') +
    '. Зарплат и аренды ' +
    'в выписке нет — их надо вписать руками.</p></div>' +
    '<div class="tscroll"><table><thead><tr><th class="l">Статья</th><th>В месяц, KGS</th>' +
    '<th>В день</th><th>За период (' +
    days +
    ' дн)</th><th class="l">Источник</th></tr></thead><tbody>'
  FIXED_ROWS.forEach(function (r) {
    var v = Number(S.fixed[r.k]) || 0
    h +=
      '<tr><td class="l">' +
      esc(r.name) +
      '</td>' +
      '<td><input type="number" step="1000" min="0" data-fix="' +
      r.k +
      '" value="' +
      v +
      '" aria-label="' +
      esc(r.name) +
      ' в месяц" style="width:110px"></td>' +
      '<td>' +
      money(v / DAYS_IN_MONTH) +
      '</td><td>' +
      money((v / DAYS_IN_MONTH) * days) +
      '</td>' +
      '<td class="l muted">' +
      esc(r.src) +
      '</td></tr>'
  })
  h +=
    "</tbody><tfoot><tr><td class='l'>Итого</td><td>" +
    money(perDay * DAYS_IN_MONTH) +
    '</td><td>' +
    money(perDay) +
    '</td><td>' +
    money(period) +
    '</td><td></td></tr></tfoot></table></div></div>'

  h +=
    '<div><div class="sec"><h2>От маржи WB к прибыли</h2>' +
    '<p>За выбранный период.</p></div><div class="tscroll"><table><tbody>' +
    row2('Выручка по ' + baseName(), tot.base) +
    row2('Комиссия WB', -tot.commission) +
    row2('Логистика', -tot.logistics) +
    row2('Реклама', -tot.ads) +
    row2('Хранение, приёмка, штрафы, удержания', -tot.other_wb) +
    row2('Себестоимость товара', -tot.cogs) +
    row2('Маржа WB', tot.margin, true) +
    row2('Постоянные расходы', -period) +
    row2('Прибыль', tot.margin - period, true) +
    '</tbody></table></div></div>'

  h +=
    '<div class="note"><b>Что сюда сознательно не попало.</b> Оплата швейной фабрике — ' +
    'это закуп товара, он ложится в себестоимость проданного, а не в расход периода. ' +
    'Подготовка товара уже сидит внутри себестоимости, второй раз её считать нельзя. ' +
    'Переводы себе и снятие наличных — вывод прибыли, а не затраты.</div></div>'
  el.innerHTML = h

  el.querySelectorAll('input[data-fix]').forEach(function (i) {
    i.addEventListener('change', function () {
      var v = parseFloat(i.value)
      S.fixed[i.dataset.fix] = isFinite(v) && v >= 0 ? v : 0
      persist()
      render()
    })
  })
}
function row2(name, v, strong) {
  return (
    "<tr><td class='l'" +
    (strong ? " style='font-weight:600'" : '') +
    '>' +
    esc(name) +
    "</td><td class='" +
    (v < 0 && strong ? 'neg' : '') +
    "'" +
    (strong ? " style='font-weight:600'" : '') +
    '>' +
    money(v) +
    '</td></tr>'
  )
}
