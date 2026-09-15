/**
 * Вкладка «Сводка»: KPI за период, графики, кто генерит маржу и что кончится.
 */
import { paretoBars } from '@/modules/labs/finmodel/bars'
import { lineChart } from '@/modules/labs/finmodel/charts'
import { $, css } from '@/modules/labs/finmodel/dom'
import { addDays, dateRu, money, nf0, nf1, pct, plural } from '@/modules/labs/finmodel/format'
import { render } from '@/modules/labs/finmodel/render'
import {
  baseName,
  baseOrders,
  buyoutOf,
  daily,
  daysToZero,
  fixedPerDay,
  revOf,
} from '@/modules/labs/finmodel/select'
import { DP, S, persist } from '@/modules/labs/finmodel/state'
import { riskTable } from '@/modules/labs/finmodel/tabs/summaryRisk'

var parExpanded = false

/* ── Сводка ─────────────────────────────────────────────────────── */
export function renderSummary(el, agg, tot, fixedPeriod, profit, days, from, to, live) {
  var buy = tot.orders ? tot.net_units / tot.orders : null
  var kpis = [
    { k: 'Выручка', v: money(tot.base), n: nf0.format(days) + ' дн, по ' + baseName(), lead: true },
    {
      k: 'Маржа WB',
      v: money(tot.margin),
      n: pct(tot.base ? tot.margin / tot.base : null) + ' выручки',
    },
    { k: 'Постоянные', v: '−' + money(fixedPeriod), n: money(fixedPerDay()) + ' в день' },
    {
      k: 'Прибыль',
      v: money(profit),
      n: pct(tot.base ? profit / tot.base : null) + ' выручки',
      lead: true,
      neg: profit < 0,
    },
    { k: 'Продано', v: nf0.format(tot.net_units), n: 'чистых единиц' },
    { k: 'Заказов', v: nf0.format(tot.orders), n: nf1.format(tot.orders / days) + ' в день' },
    { k: 'Выкуп', v: pct(buy), n: 'выкуплено на заказ' },
    {
      k: 'Средний чек',
      v: money(tot.net_units ? tot.base / tot.net_units : null),
      n: 'на единицу, по ' + baseName(),
    },
  ]
  var h = '<div class="stack">'
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

  var d = daily(from, to)
  var dates = d.map(function (x) {
    return x.d
  })
  h +=
    '<div><div class="sec"><h2>Выручка и маржа по дням</h2>' +
    '<p>Даты — дни расчёта WB. Маржа здесь после комиссии, логистики, рекламы и себестоимости, но до постоянных расходов. Реклама разнесена по дням фактической открутки: WB удерживает её одной суммой за неделю, и на дне удержания маржа проваливалась бы в минус на пустом месте.</p></div>' +
    '<div class="card"><div class="legend">' +
    '<span><span class="swatch" style="background:var(--s1)"></span>Выручка</span>' +
    '<span><span class="swatch" style="background:var(--s3)"></span>Маржа</span></div>' +
    '<div class="chartbox" id="c-rev"></div></div></div>'

  h +=
    '<div class="grid2">' +
    '<div class="card"><h3>Заказы в день</h3><p class="hint">Штук, из ленты внешних заказов</p>' +
    '<div class="chartbox" id="c-ord"></div></div>' +
    '<div class="card"><h3>Реклама в день</h3><p class="hint">KGS, датировано днём события</p>' +
    '<div class="chartbox" id="c-ads"></div></div></div>'

  // ── кто генерит: выручка и маржа в одной структуре ───────────────────
  var by = S.parBy === 'revenue' ? 'rev' : 'mar'
  var GROUPS = [
    { id: 'sku', name: 'По артикулам', one: 'артикул' },
    { id: 'subject', name: 'По предметам', one: 'предмет' },
    { id: 'brand', name: 'По брендам', one: 'бренд' },
  ]
  var grp = S.parGroup === 'subject' || S.parGroup === 'brand' ? S.parGroup : 'sku'

  var mar = []
  if (grp === 'sku') {
    mar = live
      .map(function (s2) {
        var a = agg[s2.nm_id] || {}
        return { code: s2.code, mar: a.margin || 0, rev: revOf(a), units: a.net_units || 0, n: 1 }
      })
      .filter(function (r) {
        return r.mar !== 0 || r.rev !== 0
      })
  } else {
    var box = {}
    live.forEach(function (s2) {
      var a = agg[s2.nm_id] || {}
      var m2 = a.margin || 0,
        r2 = revOf(a)
      if (!m2 && !r2) return
      var k = (grp === 'subject' ? s2.subject : s2.brand) || '(не задан)'
      var b2 = box[k] || (box[k] = { code: k, mar: 0, rev: 0, units: 0, n: 0 })
      b2.mar += m2
      b2.rev += r2
      b2.units += a.net_units || 0
      b2.n++
    })
    mar = Object.keys(box).map(function (k) {
      return box[k]
    })
  }

  var marTotal =
    mar.reduce(function (x, r) {
      return x + r.mar
    }, 0) || 1
  var revTotal =
    mar.reduce(function (x, r) {
      return x + r.rev
    }, 0) || 1
  var sorted = mar.slice().sort(function (a, b) {
    return b[by] - a[by]
  })

  // Показываем верхушку по выбранной метрике плюс всех убыточных: артикул
  // может быть крупным по выручке и при этом съедать маржу — именно такие
  // и должны попадаться на глаза.
  var KEEP = parExpanded ? sorted.length : 10
  var bars = [],
    tailM = 0,
    tailR = 0,
    tailN = 0,
    tailU = 0,
    tailNeg = 0,
    tailSku = 0
  sorted.forEach(function (r, i) {
    if (i < KEEP) {
      bars.push({
        code: r.code,
        rev: r.rev,
        mar: r.mar,
        units: r.units,
        n: r.n,
        revShare: r.rev / revTotal,
        marShare: r.mar / marTotal,
        mpct: r.rev ? r.mar / r.rev : null,
      })
    } else {
      tailM += r.mar
      tailR += r.rev
      tailU += r.units
      tailN++
      tailSku += r.n || 1
      if (r.mar < 0) tailNeg++
    }
  })
  if (tailN) {
    bars.push({
      n: tailSku,
      code:
        'ещё ' +
        tailN +
        ' ' +
        (grp === 'sku'
          ? plural(tailN, 'артикул', 'артикула', 'артикулов')
          : grp === 'subject'
            ? plural(tailN, 'предмет', 'предмета', 'предметов')
            : plural(tailN, 'бренд', 'бренда', 'брендов')),
      rev: tailR,
      mar: tailM,
      units: tailU,
      revShare: tailR / revTotal,
      marShare: tailM / marTotal,
      mpct: tailR ? tailM / tailR : null,
      dim: true,
      tail: tailN,
      tailNeg: tailNeg,
    })
  }
  var negs = mar.filter(function (r) {
    return r.mar < 0
  })
  var negSum = negs.reduce(function (x, r) {
    return x + r.mar
  }, 0)
  var negRev = negs.reduce(function (x, r) {
    return x + r.rev
  }, 0)

  var head80 = 0,
    run80 = 0
  for (var i2 = 0; i2 < sorted.length; i2++) {
    run80 += sorted[i2][by]
    head80 = i2 + 1
    if (run80 / (by === 'mar' ? marTotal : revTotal) >= 0.8) break
  }

  h +=
    '<div><div class="sec"><h2>Кто генерит выручку и маржу</h2>' +
    '<p>Доли от итогов за период: выручка ' +
    money(revTotal) +
    ', маржа ' +
    money(marTotal) +
    '. ' +
    '<b>' +
    head80 +
    ' из ' +
    mar.length +
    ' ' +
    (grp === 'sku'
      ? plural(mar.length, 'артикула', 'артикулов', 'артикулов')
      : grp === 'subject'
        ? plural(mar.length, 'предмета', 'предметов', 'предметов')
        : plural(mar.length, 'бренда', 'брендов', 'брендов')) +
    ' дают 80 % ' +
    (by === 'mar' ? 'маржи' : 'выручки') +
    '.</b>' +
    (negs.length
      ? ' Ещё ' +
        negs.length +
        ' при выручке ' +
        money(negRev) +
        ' съедают ' +
        money(-negSum) +
        ' маржи.'
      : '') +
    '</p></div>' +
    '<div class="card"><div class="filterbar" style="gap:14px">' +
    '<div class="chips">' +
    GROUPS.map(function (x) {
      return (
        '<button class="chip" type="button" data-grp="' +
        x.id +
        '" aria-pressed="' +
        (grp === x.id) +
        '">' +
        x.name +
        '</button>'
      )
    }).join('') +
    '</div>' +
    '<div class="spacer"></div>' +
    '<div class="legend" style="margin:0">' +
    '<span><span class="swatch" style="background:var(--s1)"></span>Доля в выручке</span>' +
    '<span><span class="swatch" style="background:var(--s3)"></span>Доля в марже</span></div>' +
    '<div class="chips"><button class="chip" type="button" data-par="margin" aria-pressed="' +
    (S.parBy !== 'revenue') +
    '">Сортировать по марже</button>' +
    '<button class="chip" type="button" data-par="revenue" aria-pressed="' +
    (S.parBy === 'revenue') +
    '">По выручке</button></div></div>' +
    '<div class="chartbox" id="c-par"></div>' +
    (mar.length > 10
      ? '<div style="text-align:center;margin-top:10px"><button class="btn" id="parMore" type="button">' +
        (parExpanded
          ? 'Свернуть до десяти ↑'
          : 'Показать все ' +
            mar.length +
            ' ' +
            (grp === 'sku'
              ? plural(mar.length, 'артикул', 'артикула', 'артикулов')
              : grp === 'subject'
                ? plural(mar.length, 'предмет', 'предмета', 'предметов')
                : plural(mar.length, 'бренд', 'бренда', 'брендов')) +
            ' ↓' +
            (tailNeg
              ? ' · среди скрытых ' +
                tailNeg +
                ' ' +
                plural(tailNeg, 'убыточный', 'убыточных', 'убыточных')
              : '')) +
        '</button></div>'
      : '') +
    '</div></div>'

  // ── что кончится: с ценой простоя и подсказкой ────────────────────────
  var risky = live
    .map(function (s2) {
      var a = agg[s2.nm_id] || {}
      var per = a.net_units ? a.margin / a.net_units : null
      var b2 = buyoutOf(s2),
        burn = baseOrders(s2) * b2
      var d = daysToZero(s2),
        dOff = daysToZero(s2, s2.stock.office)
      var mday = per == null ? null : burn * per
      return {
        s: s2,
        code: s2.code,
        d: d,
        dOff: dOff,
        burn: burn,
        per: per,
        mday: mday,
        avail: s2.stock.available,
        office: s2.stock.office,
        way: s2.stock.in_way_to_client,
        loss: d == null || mday == null ? null : Math.max(0, 28 - d) * mday,
        when: d == null ? null : addDays(DP.meta.stock_asof, d),
      }
    })
    .filter(function (r) {
      return r.d != null && r.d <= 21
    })
    .sort(function (a, b) {
      return a.d - b.d
    })

  var lossSum = risky.reduce(function (x, r) {
    return x + Math.max(0, r.loss || 0)
  }, 0)
  var savable = risky.filter(function (r) {
    return r.per > 0 && r.office > 0 && r.dOff != null && r.dOff > r.d + 7
  })
  var savedSum = savable.reduce(function (x, r) {
    return x + Math.max(0, r.loss || 0)
  }, 0)

  h +=
    '<div><div class="sec"><h2>Кончится в ближайшие три недели</h2>' +
    '<p>Расход = заказы в день × выкуп, только склад WB РФ и FBS. Цена простоя считается ' +
    'за 4 недели — это срок производства, то есть минимальное время без товара, если ' +
    'запускать партию прямо сейчас. Сценарий «' +
    (S.scenario === 'peak' ? 'пик' : 'текущий спрос') +
    '».</p></div>'
  if (!risky.length) {
    h +=
      '<div class="card"><p class="hint" style="margin:0">Ни один артикул не кончается в этом горизонте.</p></div>'
  } else {
    h +=
      '<div id="t-risk"></div>' +
      '<div class="grid2" style="margin-top:16px">' +
      '<div class="note flag"><b>Простой стоит ' +
      money(lossSum) +
      ' за четыре недели.</b> ' +
      (savable.length
        ? 'Из них ' +
          money(savedSum) +
          ' снимается отгрузкой офисного запаса — это ' +
          savable
            .map(function (r) {
              return r.code
            })
            .join(', ') +
          '. Товар лежит мёртвым грузом, пока артикул уходит в ноль.'
        : 'Офисный запас здесь не помогает.') +
      '</div>' +
      '<div class="note"><b>Не всякий ноль — потеря.</b> Там, где маржа на единицу ' +
      'отрицательная, исчезновение товара улучшает результат: строка помечена ' +
      '«пусть кончается». Довозить такое — значит платить за право продавать в минус.</div>' +
      '</div>'
  }
  h += '</div>'

  var m = DP.meta
  h +=
    '<div class="note flag"><b>Горизонт честности — 6–8 недель.</b> В данных два месяца ' +
    'без единого сезона: ноябрь, 11.11 и новогодний пик модель не знает. ' +
    'P&amp;L есть до ' +
    dateRu(m.pnl_to) +
    ', заказы до ' +
    dateRu(m.orders_to) +
    ', остатки замерены ' +
    dateRu(m.stock_asof) +
    '.</div></div>'
  el.innerHTML = h

  lineChart(
    $('c-rev'),
    dates,
    [
      {
        name: 'Выручка',
        color: css('--s1'),
        values: d.map(function (x) {
          return x.revenue
        }),
      },
      {
        name: 'Маржа',
        color: css('--s3'),
        values: d.map(function (x) {
          return x.margin
        }),
      },
    ],
    money,
  )
  lineChart(
    $('c-ord'),
    dates,
    [
      {
        name: 'Заказы',
        color: css('--s1'),
        values: d.map(function (x) {
          return x.orders
        }),
      },
    ],
    function (v) {
      return nf0.format(v)
    },
  )
  lineChart(
    $('c-ads'),
    dates,
    [
      {
        name: 'Реклама',
        color: css('--s2'),
        values: d.map(function (x) {
          return x.ads
        }),
      },
    ],
    money,
  )

  paretoBars($('c-par'), bars)
  el.querySelectorAll('button[data-grp]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (S.parGroup === b.dataset.grp) return
      S.parGroup = b.dataset.grp
      parExpanded = false
      persist()
      render()
    })
  })
  if ($('parMore'))
    $('parMore').addEventListener('click', function () {
      parExpanded = !parExpanded
      render()
    })
  el.querySelectorAll('button[data-par]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (S.parBy === b.dataset.par) return
      S.parBy = b.dataset.par
      persist()
      render()
    })
  })

  riskTable(risky, lossSum)
}
