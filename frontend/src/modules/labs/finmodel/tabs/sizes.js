/**
 * Размеры внутри артикула — деньги по строкам отчёта WB с баркодом.
 */
import { esc, money, nf0, num, pct } from '@/modules/labs/finmodel/format'
import { baseOrders, buyoutOf } from '@/modules/labs/finmodel/select'
import { DP, S } from '@/modules/labs/finmodel/state'
import { riskBadge } from '@/modules/labs/finmodel/table'

/* ── размеры внутри артикула ────────────────────────────────────── */
// WB не даёт размер в агрегатах отчёта о реализации, но даёт его построчно:
// выручка, комиссия, логистика и выплата по размеру измерены, а не разнесены,
// и сходятся с артикулом до копейки. Разносим только два хвоста: рекламу
// (её WB не даёт даже по артикулу) и «прочее» с нераспределённой строки.
export var expandedSkus = []
export function isExpanded(code) {
  return expandedSkus.indexOf(code) !== -1
}
export function hasSizes(code, sizeAgg) {
  var s = DP.skus.filter(function (x) {
    return x.code === code
  })[0]
  if (!s || s.nm_id == null) return false
  return !!(sizeAgg[s.nm_id] || (s.sizes || []).length)
}
function sizeLabel(x) {
  return x === '' ? 'без размера' : x
}

/** Строки по размерам за выбранный период — движение плюс размеры, лежащие в остатке. */
export function sizeRowsFor(s, a, g) {
  var rows = [],
    seen = {}
  Object.keys(g || {}).forEach(function (k) {
    var r = g[k]
    rows.push({
      size: k,
      sold: r.sold,
      returned: r.returned,
      net: r.net_units,
      revenue: r.revenue,
      card: r.card,
      commission: r.commission,
      logistics: r.logistics,
      other: r.other_wb,
      payout: r.payout,
      fwd: r.legs_fwd,
      ret: r.legs_ret,
    })
    seen[k] = 1
  })
  ;(s.sizes || []).forEach(function (x) {
    if (seen[x.size]) return
    rows.push({
      size: x.size,
      sold: 0,
      returned: 0,
      net: 0,
      revenue: 0,
      card: 0,
      commission: 0,
      logistics: 0,
      other: 0,
      payout: 0,
      fwd: 0,
      ret: 0,
    })
  })
  if (!rows.length) return rows

  var stock = {}
  ;(s.sizes || []).forEach(function (x) {
    stock[x.size] = x
  })

  var revTot = 0,
    netTot = 0,
    soldTot = 0,
    fwdTot = 0,
    baseSum = 0
  rows.forEach(function (r) {
    revTot += r.revenue
    netTot += r.net
    soldTot += r.sold
    fwdTot += r.fwd
    r.cogs = (s.cost || 0) * r.net
    r.base = r.payout - r.logistics - r.other - r.cogs
    baseSum += r.base
  })
  // невязка между суммой размеров и маржой артикула — это ровно реклама
  // и разнесённое «прочее»; кладём её на размеры по доле выручки
  var excess = baseSum - (a.margin || 0)
  rows.forEach(function (r) {
    var share = revTot ? r.revenue / revTot : netTot ? r.net / netTot : 0
    r.share = share
    r.ads = (a.ads || 0) * share
    r.margin = r.base - excess * share
    r.rev = S.revBase === 'card' ? r.card : r.revenue
    r.mpct = r.rev ? r.margin / r.rev : null
    r.logpct = r.rev ? r.logistics / r.rev : null
    r.roi = r.cogs > 0 ? r.margin / r.cogs : null
    r.price = r.net ? r.rev / r.net : null
    r.buy = r.fwd ? r.sold / r.fwd : null
    var sk = stock[r.size] || { wb: 0, fbs: 0, office: 0 }
    r.avail = (sk.wb || 0) + (sk.fbs || 0)
    r.office = sk.office || 0
    // расход берём от текущего темпа артикула, разложенного по доле продаж размера
    var perDay = baseOrders(s) * buyoutOf(s) * (soldTot ? r.sold / soldTot : 0)
    r.perDay = perDay
    r.days = perDay > 0 ? Math.round(r.avail / perDay) : null
  })
  var avg = fwdTot ? soldTot / fwdTot : null
  rows.forEach(function (r) {
    r.vs = avg != null && r.buy != null ? r.buy - avg : null
  })
  rows.sort(function (x, y) {
    return x.size.localeCompare(y.size, 'ru', { numeric: true })
  })
  return rows
}

export function sizeTable(s, a, g) {
  var rows = sizeRowsFor(s, a, g)
  if (!rows.length) return null
  var cells = [
    [
      'Размер',
      'l',
      function (r) {
        return '<span class="code">' + esc(sizeLabel(r.size)) + '</span>'
      },
    ],
    [
      'Продано',
      '',
      function (r) {
        return nf0.format(r.net)
      },
    ],
    [
      'Возвраты',
      '',
      function (r) {
        return r.returned ? nf0.format(r.returned) : '<span class="muted">—</span>'
      },
    ],
    [
      'Выкуп',
      '',
      function (r) {
        return pct(r.buy)
      },
      function (r) {
        return r.buy == null ? '' : r.buy < 0.2 ? 'neg' : r.buy > 0.35 ? 'pos' : ''
      },
    ],
    [
      'К среднему',
      '',
      function (r) {
        if (r.vs == null) return '<span class="muted">—</span>'
        return (r.vs > 0 ? '+' : '') + num(r.vs * 100, 1) + ' п.п.'
      },
      function (r) {
        return r.vs == null ? '' : r.vs < -0.05 ? 'neg' : r.vs > 0.05 ? 'pos' : ''
      },
    ],
    [
      'Цена',
      '',
      function (r) {
        return money(r.price)
      },
    ],
    [
      'Выручка',
      '',
      function (r) {
        return money(r.rev)
      },
    ],
    [
      'Комиссия',
      '',
      function (r) {
        return money(-r.commission)
      },
    ],
    [
      'Логистика',
      '',
      function (r) {
        return money(-r.logistics)
      },
    ],
    [
      'Доля лог.',
      '',
      function (r) {
        return pct(r.logpct)
      },
      function (r) {
        return r.logpct == null ? '' : r.logpct > 0.25 ? 'neg' : r.logpct < 0.12 ? 'pos' : ''
      },
    ],
    [
      'Реклама',
      '',
      function (r) {
        return money(-r.ads)
      },
    ],
    [
      'Себест.',
      '',
      function (r) {
        return money(-r.cogs)
      },
    ],
    [
      'Маржа',
      '',
      function (r) {
        return money(r.margin)
      },
      function (r) {
        return r.margin < 0 ? 'neg' : ''
      },
    ],
    [
      'Маржа %',
      '',
      function (r) {
        return pct(r.mpct)
      },
      function (r) {
        return r.mpct == null ? '' : r.mpct < 0 ? 'neg' : r.mpct > 0.4 ? 'pos' : ''
      },
    ],
    [
      'Остаток',
      '',
      function (r) {
        return nf0.format(r.avail)
      },
      function (r) {
        return r.avail === 0 && r.sold > 0 ? 'neg' : ''
      },
    ],
    [
      'В офисе',
      '',
      function (r) {
        return r.office ? nf0.format(r.office) : '<span class="muted">—</span>'
      },
    ],
    [
      'Дней до нуля',
      '',
      function (r) {
        if (r.avail === 0) return '<span class="badge b-crit">ноль</span>'
        return r.days == null ? '<span class="badge b-mute">нет продаж</span>' : riskBadge(r.days)
      },
    ],
  ]
  var titles = {
    Выкуп:
      'Продано против плеч логистики «к клиенту» за этот же период — прямое измерение, размер в строках логистики есть',
    'К среднему': 'Насколько выкуп этого размера отличается от среднего по артикулу',
    Реклама:
      'Единственная разнесённая строка: WB не даёт рекламу ни по артикулу, ни по размеру — здесь она по доле выручки размера',
    'Себест.': 'Себестоимость артикула на чистые штуки размера',
    Маржа: 'Выплата WB минус логистика, прочие удержания, себестоимость и разнесённая реклама',
    Остаток: 'Склад WB РФ + FBS по этому размеру',
    'Дней до нуля': 'Текущий темп артикула, разложенный по доле размера в продажах периода',
  }
  var sum = {
    net: 0,
    returned: 0,
    sold: 0,
    fwd: 0,
    rev: 0,
    commission: 0,
    logistics: 0,
    ads: 0,
    cogs: 0,
    margin: 0,
    avail: 0,
    office: 0,
  }
  rows.forEach(function (r) {
    sum.net += r.net
    sum.returned += r.returned
    sum.sold += r.sold
    sum.fwd += r.fwd
    sum.rev += r.rev
    sum.commission += r.commission
    sum.logistics += r.logistics
    sum.ads += r.ads
    sum.cogs += r.cogs
    sum.margin += r.margin
    sum.avail += r.avail
    sum.office += r.office
  })

  var h =
    '<div class="subwrap"><div class="subhead">Размеры артикула ' +
    esc(s.code) +
    ' · ' +
    rows.length +
    ' в сетке · деньги по строкам отчёта WB с баркодом</div>' +
    '<div class="tscroll sub"><table><thead><tr>' +
    cells
      .map(function (c) {
        return (
          '<th class="' +
          c[1] +
          '"' +
          (titles[c[0]] ? ' title="' + esc(titles[c[0]]) + '"' : '') +
          '>' +
          esc(c[0]) +
          '</th>'
        )
      })
      .join('') +
    '</tr></thead><tbody>'
  rows.forEach(function (r) {
    h +=
      '<tr>' +
      cells
        .map(function (c) {
          var cls = (c[1] ? c[1] + ' ' : '') + (c[3] ? c[3](r) : '')
          return '<td class="' + cls.trim() + '">' + c[2](r) + '</td>'
        })
        .join('') +
      '</tr>'
  })
  h +=
    '</tbody><tfoot><tr>' +
    '<td class="l">Итого по размерам</td>' +
    '<td>' +
    nf0.format(sum.net) +
    '</td>' +
    '<td>' +
    (sum.returned ? nf0.format(sum.returned) : '—') +
    '</td>' +
    '<td>' +
    pct(sum.fwd ? sum.sold / sum.fwd : null) +
    '</td>' +
    '<td></td>' +
    '<td>' +
    money(sum.net ? sum.rev / sum.net : null) +
    '</td>' +
    '<td>' +
    money(sum.rev) +
    '</td>' +
    '<td>' +
    money(-sum.commission) +
    '</td>' +
    '<td>' +
    money(-sum.logistics) +
    '</td>' +
    '<td>' +
    pct(sum.rev ? sum.logistics / sum.rev : null) +
    '</td>' +
    '<td>' +
    money(-sum.ads) +
    '</td>' +
    '<td>' +
    money(-sum.cogs) +
    '</td>' +
    '<td>' +
    money(sum.margin) +
    '</td>' +
    '<td>' +
    pct(sum.rev ? sum.margin / sum.rev : null) +
    '</td>' +
    '<td>' +
    nf0.format(sum.avail) +
    '</td>' +
    '<td>' +
    (sum.office ? nf0.format(sum.office) : '—') +
    '</td>' +
    '<td></td></tr></tfoot></table></div></div>'
  return h
}
