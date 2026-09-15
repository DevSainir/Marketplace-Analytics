/**
 * Вкладка «Реклама»: открутка кабинета, зоны показа и сверка с удержаниями WB.
 */
import { lineChart } from '@/modules/labs/finmodel/charts'
import { $, css } from '@/modules/labs/finmodel/dom'
import { dateRu, esc, money, nf0, pct } from '@/modules/labs/finmodel/format'
import { render } from '@/modules/labs/finmodel/render'
import { revOf } from '@/modules/labs/finmodel/select'
import { DP } from '@/modules/labs/finmodel/state'
import { sortState, table } from '@/modules/labs/finmodel/table'
import {
  ADS_GROUPS,
  adsView,
  adsWindow,
  adsZones,
  stackBars,
} from '@/modules/labs/finmodel/tabs/adsData'

export function renderAds(el, agg, tot, live, from, to) {
  var A = DP.ads || {}
  if (!A.available) {
    el.innerHTML =
      '<div class="note flag">Файл истории затрат на рекламу не найден. ' +
      'Положите выгрузку кабинета в <span class="code">wb_export/incoming/</span> ' +
      'и пересоберите датапак — появится сверка с удержаниями WB.</div>'
    return
  }
  var W = adsWindow(A, from, to),
    Z = adsZones(A, from, to)
  var kpis = [
    {
      k: 'Потрачено на рекламу',
      v: money(W.total),
      n: dateRu(from) + ' — ' + dateRu(to),
      lead: true,
    },
    {
      k: 'С баланса',
      v: money(W.balance),
      n: pct(W.total ? W.balance / W.total : null) + ' — ваши деньги',
    },
    {
      k: 'Промо-бонусы',
      v: money(W.promo),
      n: pct(W.total ? W.promo / W.total : null) + ' — деньги WB',
    },
    {
      k: 'ДРР',
      v: pct(tot.base ? tot.ads / tot.base : null),
      n: 'по удержаниям WB, ' + money(tot.ads),
      lead: true,
    },
  ]

  var h = '<div class="stack">'
  h +=
    '<div><div class="sec"><h2>Куда ушли деньги за период</h2>' +
    '<p>Открутка по дате списания из истории затрат кабинета. Тип ставки — оттуда же, ' +
    'зона показов — из статистики кампаний: она знает, какая часть открутки ушла в поиск, ' +
    'а какая на рекомендательные полки и прочие места.</p></div>' +
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
    '</div></div>'

  if (W.total) {
    h +=
      '<div><div class="sec"><h2>На что ушли</h2>' +
      '<p>Ручная ставка работает в поиске, единая — на полках: это видно по разнесению ' +
      'той же открутки между зонами.</p></div>' +
      '<div class="tscroll"><table><thead><tr><th class="l">Тип ставки</th>' +
      '<th>Потрачено</th><th>Доля</th><th>С баланса</th><th>Промо-бонусы</th>' +
      '<th title="Открутка в поисковой выдаче">Поиск</th>' +
      '<th title="Рекомендательные полки, карточка товара и прочие места показа">Полки и прочее</th>' +
      '<th>Доля поиска</th></tr></thead><tbody>'
    W.kinds.forEach(function (k) {
      var z = Z.byKind[k.name] || { search: null, rest: null, share: null }
      h +=
        '<tr><td class="l">' +
        esc(k.name) +
        '</td><td>' +
        money(k.total) +
        '</td><td>' +
        pct(W.total ? k.total / W.total : null) +
        '</td><td>' +
        money(k.balance) +
        '</td><td>' +
        (k.promo ? money(k.promo) : '<span class="muted">—</span>') +
        '</td><td>' +
        (z.share == null ? '<span class="muted">нет данных</span>' : money(k.total * z.share)) +
        '</td><td>' +
        (z.share == null ? '<span class="muted">—</span>' : money(k.total * (1 - z.share))) +
        '</td><td>' +
        pct(z.share) +
        '</td></tr>'
    })
    h +=
      "</tbody><tfoot><tr><td class='l'>Итого</td><td>" +
      money(W.total) +
      '</td><td>' +
      pct(W.total ? 1 : null) +
      '</td><td>' +
      money(W.balance) +
      '</td><td>' +
      money(W.promo) +
      '</td><td>' +
      (Z.share == null ? '—' : money(W.total * Z.share)) +
      '</td><td>' +
      (Z.share == null ? '—' : money(W.total * (1 - Z.share))) +
      '</td><td>' +
      pct(Z.share) +
      '</td></tr></tfoot></table></div>'
    if (Z.share != null) {
      h +=
        '<div class="card" style="margin-top:14px"><h3>Зоны показов</h3>' +
        '<p class="hint">Доля измерена по статистике кампаний за ' +
        Z.days +
        ' дн периода и приложена к деньгам кабинета.</p>' +
        '<div class="legend">' +
        '<span><span class="swatch sq" style="background:var(--s1)"></span>Поиск</span>' +
        '<span><span class="swatch sq" style="background:var(--s2)"></span>Полки и прочее</span>' +
        '</div>' +
        stackBars(
          [{ label: 'Вся реклама', parts: [W.total * Z.share, W.total * (1 - Z.share)] }].concat(
            W.kinds
              .filter(function (k) {
                return Z.byKind[k.name]
              })
              .map(function (k) {
                var z = Z.byKind[k.name]
                return { label: k.name, parts: [k.total * z.share, k.total * (1 - z.share)] }
              }),
          ),
        ) +
        '</div>'
    }
    h += '</div>'
  }

  var dd = A.daily.filter(function (r) {
    return r[0] >= from && r[0] <= to
  })
  if (dd.length > 1) {
    h +=
      '<div><div class="sec"><h2>Открутка по дням</h2>' +
      '<p>Дата списания из кабинета, за выбранный вверху период.</p></div>' +
      '<div class="card"><div class="legend">' +
      '<span><span class="swatch" style="background:var(--s1)"></span>С баланса</span>' +
      '<span><span class="swatch" style="background:var(--s2)"></span>Промо-бонусы</span></div>' +
      '<div class="chartbox" id="c-adsd"></div></div></div>'
  }

  var base = live
    .map(function (s2) {
      var a = agg[s2.nm_id] || {},
        hst = s2.ads_hist || {}
      var ads = a.ads || 0,
        rev = revOf(a)
      return {
        code: s2.code,
        subject: s2.subject || '—',
        brand: s2.brand || '—',
        ads: ads,
        rev: rev,
        orders: a.orders || 0,
        promo: hst.promo || 0,
      }
    })
    .filter(function (r) {
      return r.ads > 0 || r.rev > 0
    })

  var subjects = [],
    brands = []
  base.forEach(function (r) {
    if (subjects.indexOf(r.subject) === -1) subjects.push(r.subject)
    if (brands.indexOf(r.brand) === -1) brands.push(r.brand)
  })
  subjects.sort(function (a, b) {
    return a.localeCompare(b, 'ru')
  })
  brands.sort(function (a, b) {
    return a.localeCompare(b, 'ru')
  })

  var q = adsView.q.trim().toLowerCase()
  var picked = base.filter(function (r) {
    if (adsView.subject && r.subject !== adsView.subject) return false
    if (adsView.brand && r.brand !== adsView.brand) return false
    if (
      q &&
      r.code.toLowerCase().indexOf(q) === -1 &&
      r.subject.toLowerCase().indexOf(q) === -1 &&
      r.brand.toLowerCase().indexOf(q) === -1
    )
      return false
    return true
  })

  // группировка: те же деньги, только зерно крупнее
  var rows = picked
  if (adsView.group !== 'sku') {
    var by = {}
    picked.forEach(function (r) {
      var key = r[adsView.group]
      var g = by[key] || (by[key] = { code: key, ads: 0, rev: 0, orders: 0, promo: 0, n: 0 })
      g.ads += r.ads
      g.rev += r.rev
      g.orders += r.orders
      g.promo += r.promo
      g.n++
    })
    rows = Object.keys(by).map(function (k) {
      return by[k]
    })
  }
  rows.forEach(function (r) {
    r.drr = r.rev ? r.ads / r.rev : null
  })

  var sum = { ads: 0, rev: 0, orders: 0, promo: 0 }
  rows.forEach(function (r) {
    sum.ads += r.ads
    sum.rev += r.rev
    sum.orders += r.orders
    sum.promo += r.promo
  })

  var groupDef = ADS_GROUPS.filter(function (g) {
    return g.id === adsView.group
  })[0]
  var cols = [
    {
      key: 'code',
      name: groupDef.col,
      l: true,
      get: function (r) {
        return (
          '<span class="code">' +
          esc(r.code) +
          '</span>' +
          (r.n ? ' <span class="muted">· ' + r.n + '</span>' : '')
        )
      },
    },
    {
      key: 'ads',
      name: 'Реклама',
      sort: true,
      get: function (r) {
        return money(r.ads)
      },
    },
    {
      key: 'drr',
      name: 'ДРР',
      title: 'Доля рекламы в выручке артикула',
      get: function (r) {
        return pct(r.drr)
      },
      cls: function (r) {
        return r.drr > 0.2 ? 'neg' : ''
      },
    },
    {
      key: 'orders',
      name: 'Заказы',
      get: function (r) {
        return nf0.format(r.orders)
      },
    },
    {
      key: 'rev',
      name: 'Выручка',
      get: function (r) {
        return money(r.rev)
      },
    },
    {
      key: 'promo',
      name: 'Промо-бонусы',
      title: 'Часть открутки, оплаченная бонусами WB, за всё окно',
      get: function (r) {
        return r.promo ? money(r.promo) : '<span class="muted">—</span>'
      },
    },
  ]
  var foot = {
    code:
      'Итого ' +
      rows.length +
      (rows.length < base.length && adsView.group === 'sku' ? ' из ' + base.length : ''),
    ads: money(sum.ads),
    drr: pct(sum.rev ? sum.ads / sum.rev : null),
    orders: nf0.format(sum.orders),
    rev: money(sum.rev),
    promo: money(sum.promo),
  }

  h +=
    '<div><div class="sec"><h2>Реклама по ' +
    groupDef.by +
    '</h2>' +
    '<p>За выбранный вверху период, суммы разнесены из удержаний WB по долям фактической ' +
    'открутки. Промо-бонусы — за всё окно файла кабинета: по дням они приходят без ' +
    'артикула.</p></div>' +
    '<div class="filterbar">' +
    '<input type="search" id="adsQ" placeholder="Поиск по артикулу, предмету, бренду" value="' +
    esc(adsView.q) +
    '" aria-label="Поиск по артикулу">' +
    '<div class="chips" role="group" aria-label="Группировка">' +
    ADS_GROUPS.map(function (g) {
      return (
        '<button class="chip" data-adsgrp="' +
        g.id +
        '" type="button" aria-pressed="' +
        (adsView.group === g.id ? 'true' : 'false') +
        '">' +
        g.name +
        '</button>'
      )
    }).join('') +
    '</div>' +
    '<select id="adsSubj" aria-label="Фильтр по предмету"><option value="">Все предметы</option>' +
    subjects
      .map(function (x) {
        return (
          '<option value="' +
          esc(x) +
          '"' +
          (adsView.subject === x ? ' selected' : '') +
          '>' +
          esc(x) +
          '</option>'
        )
      })
      .join('') +
    '</select>' +
    '<select id="adsBrand" aria-label="Фильтр по бренду"><option value="">Все бренды</option>' +
    brands
      .map(function (x) {
        return (
          '<option value="' +
          esc(x) +
          '"' +
          (adsView.brand === x ? ' selected' : '') +
          '>' +
          esc(x) +
          '</option>'
        )
      })
      .join('') +
    '</select>' +
    (q || adsView.subject || adsView.brand
      ? '<button class="btn" id="adsClear" type="button">Сбросить фильтр</button>'
      : '') +
    '</div><div id="t-ads"></div></div>'

  h +=
    '<div class="grid2">' +
    '<div class="note flag"><b>Отчётные периоды идут не встык.</b> ' +
    A.gaps
      .map(function (g) {
        return dateRu(g.from) + ' — ' + dateRu(g.to)
      })
      .join(', ') +
    ' не покрыты ни одним отчётом, а открутка за эти дни — ' +
    money(
      A.gaps.reduce(function (a2, g) {
        return a2 + g.spent
      }, 0),
    ) +
    ' — сидит в следующем удержании. Модель растягивает окно разнесения на эти дни, ' +
    'иначе недельная трата схлопывалась бы в два дня и выбивала маржу в минус.</div>' +
    '<div class="note"><b>Удержано на ' +
    money(A.residual) +
    ' больше, чем откручено (' +
    (A.residual_pct > 0 ? '+' : '') +
    A.residual_pct +
    ' %).</b> Часть объясняется хвостом: ' +
    'до начала первого отчётного периода откручено ' +
    money(A.before_window) +
    ', и первое удержание частично забирает его. ' +
    (A.no_article
      ? 'Ещё ' +
        money(A.no_article) +
        ' приходится на кампании без артикула в названии — ' +
        'они разносятся по общей доле. '
      : '') +
    'Остаток стоит уточнить в поддержке WB.</div></div>'

  h +=
    '<div class="note"><b>Промо-бонусы — это не ваши деньги.</b> ' +
    money(W.promo) +
    ' из ' +
    money(W.total) +
    ' открутки за период оплачено бонусами WB. ' +
    'В удержания они попадают наравне с балансом, поэтому в марже учтены, но при оценке ' +
    'собственных вложений в рекламу эту сумму надо держать отдельно.</div></div>'

  el.innerHTML = h
  table($('t-ads'), 'ads', cols, rows, foot, null, {
    n: 10,
    isOpen: function () {
      return adsView.all
    },
    toggle: function () {
      adsView.all = !adsView.all
    },
  })

  var aq = $('adsQ')
  aq.addEventListener('input', function () {
    adsView.q = aq.value
    var pos = aq.selectionStart
    render()
    var again = $('adsQ')
    if (again) {
      again.focus()
      try {
        again.setSelectionRange(pos, pos)
      } catch {
        /* noop */
      }
    }
  })
  $('adsSubj').addEventListener('change', function () {
    adsView.subject = this.value
    render()
  })
  $('adsBrand').addEventListener('change', function () {
    adsView.brand = this.value
    render()
  })
  if ($('adsClear'))
    $('adsClear').addEventListener('click', function () {
      adsView.q = ''
      adsView.subject = ''
      adsView.brand = ''
      render()
    })
  el.querySelectorAll('button[data-adsgrp]').forEach(function (b) {
    b.addEventListener('click', function () {
      adsView.group = b.dataset.adsgrp
      sortState.ads = { key: 'ads', dir: -1 }
      render()
    })
  })
  if (dd.length > 1) {
    lineChart(
      $('c-adsd'),
      dd.map(function (r) {
        return r[0]
      }),
      [
        {
          name: 'С баланса',
          color: css('--s1'),
          values: dd.map(function (r) {
            return r[1]
          }),
        },
        {
          name: 'Промо-бонусы',
          color: css('--s2'),
          values: dd.map(function (r) {
            return r[2]
          }),
        },
      ],
      money,
    )
  }
}
