/**
 * Вкладка «Прогноз»: посуточная симуляция на выбранный горизонт.
 */
import { barChart } from '@/modules/labs/finmodel/charts'
import { $, css } from '@/modules/labs/finmodel/dom'
import { addDays, dateRu, esc, money, nf0, num, pct } from '@/modules/labs/finmodel/format'
import { render } from '@/modules/labs/finmodel/render'
import {
  baseOrders,
  buyoutOf,
  econ,
  fixedPerDay,
  growthOf,
  simulate,
} from '@/modules/labs/finmodel/select'
import { DP, S, persist } from '@/modules/labs/finmodel/state'
import { table } from '@/modules/labs/finmodel/table'

/* ── Прогноз ────────────────────────────────────────────────────── */
export function renderForecast(el, agg, live) {
  var weeks = S.horizon,
    horizonDays = weeks * 7
  var sn = (DP.monitoring || {}).season || {}
  var perWeek = [],
    totals = { revenue: 0, margin: 0, sales: 0, orders: 0, ads: 0, cogs: 0 }
  for (var w = 0; w < weeks; w++)
    perWeek.push({ revenue: 0, margin: 0, sales: 0, orders: 0, ads: 0 })

  var detail = []
  live.forEach(function (s) {
    var e = econ(s, agg)
    if (!e) return
    var sim = simulate(s, horizonDays, e)
    var row = {
      code: s.code,
      revenue: 0,
      margin: 0,
      sales: 0,
      orders: 0,
      ads: 0,
      base: baseOrders(s),
      growth: growthOf(s),
      buy: buyoutOf(s),
      oos: sim.oosDay,
      stock: s.stock.available,
      fromSlice: e.fromSlice,
      cheque: e.cheque,
      s: s,
    }
    sim.days.forEach(function (d, i) {
      var w2 = Math.floor(i / 7)
      perWeek[w2].revenue += d.revenue
      perWeek[w2].margin += d.margin
      perWeek[w2].sales += d.sales
      perWeek[w2].orders += d.orders
      perWeek[w2].ads += d.ads
      row.revenue += d.revenue
      row.margin += d.margin
      row.sales += d.sales
      row.orders += d.orders
      row.ads += d.ads
      totals.cogs += d.cogs
    })
    totals.revenue += row.revenue
    totals.margin += row.margin
    totals.sales += row.sales
    totals.orders += row.orders
    totals.ads += row.ads
    detail.push(row)
  })

  var fixedWeek = fixedPerDay() * 7
  var fixedTotal = fixedPerDay() * horizonDays
  var profit = totals.margin - fixedTotal

  var h = '<div class="stack">'
  h +=
    '<div><div class="sec"><h2>Допущения прогноза</h2>' +
    '<p>Юнит-экономика каждого артикула берётся из выбранного вверху периода: средний чек, ' +
    'комиссия, логистика и реклама на заказ, себестоимость. Спрос — из последних ' +
    '14 дней заказов. Рост правится по артикулам ' +
    'в таблице ниже и на вкладке остатков.</p></div>' +
    '<div class="card"><div class="assump">' +
    '<div class="field"><label for="fHor">Горизонт, недель</label>' +
    '<input type="number" id="fHor" min="1" max="26" value="' +
    weeks +
    '">' +
    '<span class="why">Дальше 8 недель модель экстраполирует лето на осень.</span></div>' +
    '<div class="field"><label for="fScen">Сценарий спроса</label>' +
    '<select id="fScen"><option value="base"' +
    (S.scenario === 'base' ? ' selected' : '') +
    '>Текущий спрос — последние 14 дней</option><option value="peak"' +
    (S.scenario === 'peak' ? ' selected' : '') +
    '>Пик — полный размерный ряд и реклама</option></select>' +
    '<span class="why">Пик измерен по дням, когда размерное покрытие было на максимуме, ' +
    'а реклама не ниже медианы.</span></div>' +
    '<div class="field"><label for="fAds">Реклама, множитель к истории</label>' +
    '<input type="number" id="fAds" step="0.1" min="0" value="' +
    S.adMult +
    '">' +
    '<span class="why">1.0 — тратим столько же на заказ, сколько тратили в выбранном периоде.</span></div>' +
    '<div class="field"><label for="fLim"><input type="checkbox" id="fLim"' +
    (S.limitByStock ? ' checked' : '') +
    '> Останавливать продажи, когда склад пуст</label>' +
    '<span class="why">Без этого прогноз продаёт товар, которого нет: шесть артикулов ' +
    'кончаются в первую неделю.</span></div>' +
    (sn.available
      ? '<div class="field"><label for="fSeason"><input type="checkbox" id="fSeason"' +
        (S.season ? ' checked' : '') +
        '> Сезонная поправка выкупа</label>' +
        '<span class="why">В ноябре–декабре выкуп проседает на ' +
        num(sn.delta_pp, 1) +
        ' п.п. (×' +
        num(sn.factor, 2) +
        '). Измерено на корзине из ' +
        sn.basket_size +
        ' артикулов за один год — ориентир, не статистика.</span></div>'
      : '') +
    '</div></div></div>'

  var kpis = [
    { k: 'Выручка за ' + weeks + ' нед', v: money(totals.revenue), n: 'KGS', lead: true },
    {
      k: 'Маржа WB',
      v: money(totals.margin),
      n: pct(totals.revenue ? totals.margin / totals.revenue : null),
    },
    { k: 'Постоянные', v: '−' + money(fixedTotal), n: money(fixedWeek) + ' в неделю' },
    {
      k: 'Прибыль',
      v: money(profit),
      n: pct(totals.revenue ? profit / totals.revenue : null),
      lead: true,
      neg: profit < 0,
    },
    { k: 'Продаж', v: nf0.format(Math.round(totals.sales)), n: 'единиц' },
    {
      k: 'Заказов',
      v: nf0.format(Math.round(totals.orders)),
      n: nf0.format(totals.orders / horizonDays) + ' в день',
    },
    { k: 'Реклама', v: money(totals.ads), n: 'за горизонт' },
    { k: 'В среднем в неделю', v: money(profit / weeks), n: 'прибыли' },
  ]
  h +=
    '<div class="kpis">' +
    kpis
      .map(function (x) {
        return (
          '<div class="kpi' +
          (x.lead ? ' lead' : '') +
          '"><div class="k">' +
          x.k +
          '</div><div class="v' +
          (x.neg ? ' neg' : '') +
          '">' +
          x.v +
          '</div><div class="n">' +
          x.n +
          '</div></div>'
        )
      })
      .join('') +
    '</div>'

  h +=
    '<div><div class="sec"><h2>По неделям</h2><p>Прибыль — маржа минус постоянные расходы, ' +
    money(fixedWeek) +
    ' в неделю.</p></div><div class="card"><div class="legend">' +
    '<span><span class="swatch sq" style="background:var(--s1)"></span>Выручка</span>' +
    '<span><span class="swatch sq" style="background:var(--s3)"></span>Прибыль после постоянных</span></div>' +
    '<div class="chartbox" id="c-fc"></div></div></div>'

  var cols = [
    {
      key: 'code',
      name: 'Артикул',
      l: true,
      get: function (r) {
        return '<span class="code">' + esc(r.code) + '</span>'
      },
    },
    {
      key: 'stock',
      name: 'Доступно',
      get: function (r) {
        return nf0.format(r.stock)
      },
    },
    {
      key: 'base',
      name: 'Заказы/д',
      get: function (r) {
        return num(r.base, 1)
      },
    },
    {
      key: 'buy',
      name: 'Выкуп',
      get: function (r) {
        return pct(r.buy)
      },
    },
    {
      key: 'growth',
      name: 'Рост %/нед',
      get: function (r) {
        return (
          '<input type="number" step="1" data-g2="' +
          esc(r.code) +
          '" value="' +
          r.growth +
          '" aria-label="Рост заказов ' +
          esc(r.code) +
          '">'
        )
      },
      sortable: false,
    },
    {
      key: 'oos',
      name: 'Кончится',
      title: 'На какой день горизонта склад уйдёт в ноль',
      get: function (r) {
        return r.oos == null
          ? '<span class="badge b-good">хватит</span>'
          : '<span class="badge ' +
              (r.oos <= 14 ? 'b-crit' : 'b-warn') +
              '">' +
              'день ' +
              (r.oos + 1) +
              '</span>'
      },
    },
    {
      key: 'orders',
      name: 'Заказов',
      get: function (r) {
        return nf0.format(Math.round(r.orders))
      },
    },
    {
      key: 'sales',
      name: 'Продаж',
      get: function (r) {
        return nf0.format(Math.round(r.sales))
      },
    },
    {
      key: 'cheque',
      name: 'Ср. чек',
      get: function (r) {
        return money(r.cheque)
      },
    },
    {
      key: 'revenue',
      name: 'Выручка',
      sort: true,
      get: function (r) {
        return money(r.revenue)
      },
    },
    {
      key: 'ads',
      name: 'Реклама',
      get: function (r) {
        return money(-r.ads)
      },
    },
    {
      key: 'margin',
      name: 'Маржа',
      get: function (r) {
        return money(r.margin)
      },
      cls: function (r) {
        return r.margin < 0 ? 'neg' : ''
      },
    },
  ]
  var foot = {
    code: 'Итого ' + detail.length,
    stock: nf0.format(
      detail.reduce(function (a, r) {
        return a + r.stock
      }, 0),
    ),
    orders: nf0.format(Math.round(totals.orders)),
    sales: nf0.format(Math.round(totals.sales)),
    revenue: money(totals.revenue),
    ads: money(-totals.ads),
    margin: money(totals.margin),
  }

  h +=
    '<div><div class="sec"><h2>Прогноз по артикулам</h2>' +
    '<p>Коэффициент роста задаётся отдельно для каждого артикула и применяется понедельно, ' +
    'с накоплением. Артикулы без истории продаж в прогноз не попадают.</p></div>' +
    '<div id="t-fc"></div></div>'

  h +=
    '<div class="grid2"><div class="note"><b>Деньги приходят позже прибыли.</b> ' +
    'От заказа до денег на счёте измеренные 25.5 дня: 7.1 дня до выкупа, расчёт WB в тот же день, ' +
    'до недели ожидания конца периода, день на отчёт и 15 дней до платежа. ' +
    'Прибыль первой недели горизонта окажется на счёте примерно ' +
    dateRu(addDays(DP.meta.stock_asof, 29)) +
    '.</div>' +
    '<div class="note flag"><b>Что прогноз не умеет.</b> В данных нет ни одного сезона и ни одной ' +
    'поставки: модель не знает ноябрь и не знает, что вы запустили в производство. ' +
    'Приход товара она увидит только после того, как вы обновите замер остатков.</div></div></div>'

  el.innerHTML = h
  table($('t-fc'), 'fc', cols, detail, foot)

  barChart(
    $('c-fc'),
    perWeek.map(function (_, i) {
      return 'нед ' + (i + 1)
    }),
    [
      {
        name: 'Выручка',
        color: css('--s1'),
        values: perWeek.map(function (x) {
          return x.revenue
        }),
      },
      {
        name: 'Прибыль',
        color: css('--s3'),
        values: perWeek.map(function (x) {
          return x.margin - fixedWeek
        }),
      },
    ],
    money,
  )

  $('fHor').addEventListener('change', function () {
    var v = parseInt(this.value, 10)
    if (v >= 1 && v <= 26) {
      S.horizon = v
      persist()
      render()
    }
  })
  $('fScen').addEventListener('change', function () {
    S.scenario = this.value
    persist()
    render()
  })
  $('fAds').addEventListener('change', function () {
    var v = parseFloat(this.value)
    if (isFinite(v) && v >= 0) {
      S.adMult = v
      persist()
      render()
    }
  })
  $('fLim').addEventListener('change', function () {
    S.limitByStock = this.checked
    persist()
    render()
  })
  if ($('fSeason'))
    $('fSeason').addEventListener('change', function () {
      S.season = this.checked
      persist()
      render()
    })
  el.querySelectorAll('input[data-g2]').forEach(function (i) {
    i.addEventListener('change', function () {
      var v = parseFloat(i.value)
      if (isFinite(v) && v !== 0) S.growth[i.dataset.g2] = v
      else delete S.growth[i.dataset.g2]
      persist()
      render()
    })
  })
}
