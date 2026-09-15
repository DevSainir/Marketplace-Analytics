/**
 * Вкладка «Остатки и аут-оф-сток».
 */
import { hbars } from '@/modules/labs/finmodel/bars'
import { $ } from '@/modules/labs/finmodel/dom'
import { addDays, dateRu, esc, nf0, num } from '@/modules/labs/finmodel/format'
import { render } from '@/modules/labs/finmodel/render'
import { baseOrders, buyoutOf, daysToZero, growthOf } from '@/modules/labs/finmodel/select'
import { DP, S, persist } from '@/modules/labs/finmodel/state'
import { riskBadge, sortState, table } from '@/modules/labs/finmodel/table'

/* ── Остатки и аут-оф-сток ──────────────────────────────────────── */
export function renderOos(el, agg, live) {
  var rows = live
    .concat(
      DP.skus.filter(function (s) {
        return s.nm_id == null
      }),
    )
    .filter(function (s) {
      return s.stock.total > 0 || s.base_orders_per_day > 0
    })
    .map(function (s) {
      var b = buyoutOf(s),
        base = baseOrders(s),
        burn = base * b
      var d = daysToZero(s),
        dOff = daysToZero(s, s.stock.office)
      return {
        s: s,
        code: s.code,
        wb: s.stock.wb,
        fbs: s.stock.fbs,
        avail: s.stock.available,
        office: s.stock.office,
        way: s.stock.in_way_to_client,
        back: s.stock.in_way_back,
        sizes: s.stock.sizes_total ? s.stock.sizes_in_stock / s.stock.sizes_total : null,
        base: base,
        buy: b,
        burn: burn,
        d: d == null ? null : d,
        dOff: dOff == null ? null : dOff,
        when: d == null ? null : addDays(DP.meta.stock_asof, d),
      }
    })

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
      key: 'wb',
      name: 'Склад WB',
      get: function (r) {
        return nf0.format(r.wb)
      },
    },
    {
      key: 'fbs',
      name: 'FBS',
      get: function (r) {
        return nf0.format(r.fbs)
      },
    },
    {
      key: 'avail',
      name: 'Доступно',
      title: 'Только то, что реально продаётся: склад WB РФ + FBS',
      get: function (r) {
        return '<b>' + nf0.format(r.avail) + '</b>'
      },
    },
    {
      key: 'sizes',
      name: 'Размеры',
      title: 'Сколько размеров есть в наличии из всех заведённых',
      get: function (r) {
        if (r.sizes == null) return '<span class="muted">—</span>'
        var cl = r.sizes >= 0.9 ? 'b-good' : r.sizes >= 0.6 ? 'b-warn' : 'b-crit'
        return (
          '<span class="badge ' +
          cl +
          '">' +
          r.s.stock.sizes_in_stock +
          ' / ' +
          r.s.stock.sizes_total +
          '</span>'
        )
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
      key: 'src',
      name: 'Источник выкупа',
      l: true,
      sortable: false,
      title: 'Откуда взята доля выкупа для этого артикула',
      get: function (r) {
        var t = r.s.buyout_source || ''
        var cl =
          t.indexOf('воронка') === 0 ? 'b-good' : t.indexOf('лента') === 0 ? 'b-warn' : 'b-mute'
        var short =
          t.indexOf('воронка') === 0 ? 'воронка WB' : t.indexOf('лента') === 0 ? 'лента' : 'P&L'
        return '<span class="badge ' + cl + '" title="' + esc(t) + '">' + short + '</span>'
      },
    },
    {
      key: 'buy',
      name: 'Выкуп',
      get: function (r) {
        return (
          '<input type="number" step="0.01" min="0" max="1" data-buy="' +
          esc(r.code) +
          '" value="' +
          (r.buy ? r.buy.toFixed(2) : '') +
          '" aria-label="Выкуп ' +
          esc(r.code) +
          '">'
        )
      },
      sortable: false,
    },
    {
      key: 'growth',
      name: 'Рост %/нед',
      get: function (r) {
        return (
          '<input type="number" step="1" data-growth="' +
          esc(r.code) +
          '" value="' +
          growthOf(r.s) +
          '" aria-label="Рост заказов ' +
          esc(r.code) +
          '">'
        )
      },
      sortable: false,
    },
    {
      key: 'burn',
      name: 'Расход/д',
      title: 'Заказы в день × выкуп',
      get: function (r) {
        return num(r.burn, 1)
      },
    },
    {
      key: 'd',
      name: 'Дней до нуля',
      sort: true,
      get: function (r) {
        return riskBadge(r.d)
      },
    },
    {
      key: 'when',
      name: 'Дата',
      get: function (r) {
        return r.when ? dateRu(r.when) : '<span class="muted">—</span>'
      },
    },
    {
      key: 'office',
      name: 'В офисе',
      title: 'Лежит мёртво, в продаже не участвует',
      get: function (r) {
        return r.office ? nf0.format(r.office) : '<span class="muted">—</span>'
      },
    },
    {
      key: 'dOff',
      name: 'Если отгрузить',
      title: 'Дней до нуля, если офисный запас уйдёт на склад',
      get: function (r) {
        return r.office && r.dOff != null && r.d != null && r.dOff > r.d
          ? '<span class="badge b-good">' + r.dOff + ' дн</span>'
          : '<span class="muted">—</span>'
      },
    },
    {
      key: 'way',
      name: 'В пути',
      title: 'Едет к клиентам, вернётся в среднем на 70 %',
      get: function (r) {
        return nf0.format(r.way)
      },
    },
    {
      key: 'back',
      name: 'Возвраты',
      get: function (r) {
        return nf0.format(r.back)
      },
    },
  ]
  sortState.oos = sortState.oos || { key: 'd', dir: 1 }

  var sumAvail = rows.reduce(function (a, r) {
    return a + r.avail
  }, 0)
  var sumOff = rows.reduce(function (a, r) {
    return a + r.office
  }, 0)
  var sumWay = rows.reduce(function (a, r) {
    return a + r.way
  }, 0)
  var sumBack = rows.reduce(function (a, r) {
    return a + r.back
  }, 0)
  var foot = {
    code: 'Итого ' + rows.length,
    wb: nf0.format(
      rows.reduce(function (a, r) {
        return a + r.wb
      }, 0),
    ),
    fbs: nf0.format(
      rows.reduce(function (a, r) {
        return a + r.fbs
      }, 0),
    ),
    avail: nf0.format(sumAvail),
    office: nf0.format(sumOff),
    way: nf0.format(sumWay),
    back: nf0.format(sumBack),
    burn: num(
      rows.reduce(function (a, r) {
        return a + r.burn
      }, 0),
      1,
    ),
  }

  var soon = rows
    .filter(function (r) {
      return r.d != null && r.d <= 60
    })
    .sort(function (a, b) {
      return a.d - b.d
    })
    .slice(0, 16)

  var h =
    '<div class="stack"><div><div class="sec"><h2>Когда кончится каждый артикул</h2>' +
    '<p>Считается только то, что лежит на складе WB РФ и на складе FBS у фулфилмента: именно этот ' +
    'товар продаётся. Офис и товар в петле доставки в расход не идут. Выкуп и рост заказов правятся ' +
    'прямо в таблице — модель пересчитывается сразу.</p></div>'

  if (soon.length) {
    h +=
      '<div class="card"><h3>Дней до нуля</h3>' +
      '<p class="hint">Красное — две недели и меньше, охра — до пяти недель. Шкала обрезана на 60 днях.</p>' +
      '<div id="c-oos"></div></div>'
  }
  h += '<div id="t-oos" style="margin-top:18px"></div></div>'

  h +=
    '<div class="grid2">' +
    '<div class="note"><b>Что в остатках заморожено.</b> На полке ' +
    nf0.format(sumAvail) +
    ' шт, в петле доставки ' +
    nf0.format(sumWay + sumBack) +
    ' шт (едут к клиентам и обратно), ' +
    'в офисе ' +
    nf0.format(sumOff) +
    ' шт. Петля — прямое следствие выкупа около 27 %: ' +
    'на каждую продажу приходится больше трёх поездок.</div>' +
    '<div class="note flag"><b>Минимальная партия — 500 штук, срок — 4 недели.</b> ' +
    'Сверяйте колонку «Дней до нуля» с расходом: там, где расход меньше 2–3 штук в день, ' +
    'партия в 500 единиц оборачивается годами. Запускать в производство стоит то, что ' +
    'быстро оборачивается, а не то, что первым кончается.</div></div></div>'

  el.innerHTML = h
  table($('t-oos'), 'oos', cols, rows, foot)

  if (soon.length) hbars($('c-oos'), soon)

  el.querySelectorAll('input[data-buy]').forEach(function (i) {
    i.addEventListener('change', function () {
      var v = parseFloat(i.value)
      if (isFinite(v) && v > 0 && v <= 1) S.buyout[i.dataset.buy] = v
      else delete S.buyout[i.dataset.buy]
      persist()
      render()
    })
  })
  el.querySelectorAll('input[data-growth]').forEach(function (i) {
    i.addEventListener('change', function () {
      var v = parseFloat(i.value)
      if (isFinite(v) && v !== 0) S.growth[i.dataset.growth] = v
      else delete S.growth[i.dataset.growth]
      persist()
      render()
    })
  })
}

/** Две полосы на артикул — доля в выручке и доля в марже — в одной шкале
    долей, плюс накопительный процент по активной сортировке. Отрицательная
    маржа рисуется красным влево от нуля. При наведении на полосу подсказка
    называет метрику и показывает абсолютные суммы. */
