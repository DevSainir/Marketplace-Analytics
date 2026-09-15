/**
 * Вкладка «Артикулы»: что принёс каждый артикул за период.
 */
import { $ } from '@/modules/labs/finmodel/dom'
import { esc, money, nf0, pct } from '@/modules/labs/finmodel/format'
import { ICO_PIN_OFF, ICO_PIN_ON, ICO_TRI } from '@/modules/labs/finmodel/icons'
import { render } from '@/modules/labs/finmodel/render'
import { baseName, revOf } from '@/modules/labs/finmodel/select'
import { S, persist } from '@/modules/labs/finmodel/state'
import { table } from '@/modules/labs/finmodel/table'
import { expandedSkus, hasSizes, isExpanded, sizeTable } from '@/modules/labs/finmodel/tabs/sizes'

/* ── Артикулы ───────────────────────────────────────────────────── */
var skuFilter = { q: '', subject: '' }

function isPinned(code) {
  return S.pinned.indexOf(code) !== -1
}
function togglePin(code) {
  var i = S.pinned.indexOf(code)
  if (i === -1) S.pinned.push(code)
  else S.pinned.splice(i, 1)
  persist()
  render()
}

export function renderSkus(el, agg, tot, live, sizeAgg) {
  var all = live
    .map(function (s) {
      var a = agg[s.nm_id] || {}
      var rev = revOf(a),
        net = a.net_units || 0,
        ord = a.orders || 0
      var card = a.card || 0,
        gross = a.revenue || 0
      return {
        sku: s,
        code: s.code,
        subject: s.subject,
        net: net,
        orders: ord,
        rev: rev,
        cheque: net ? rev / net : null,
        card: net ? card / net : null,
        gross: net ? gross / net : null,
        spp: card ? 1 - gross / card : null,
        comm: a.commission || 0,
        log: a.logistics || 0,
        ads: a.ads || 0,
        other: a.other_wb || 0,
        cogs: a.cogs || 0,
        margin: a.margin || 0,
        mpct: rev ? (a.margin || 0) / rev : null,
        drr: rev ? (a.ads || 0) / rev : null,
        buy: ord ? net / ord : null,
        logo: ord ? (a.logistics || 0) / ord : null,
        roi: (a.cogs || 0) > 0 ? (a.margin || 0) / a.cogs : null,
        logpct: rev ? (a.logistics || 0) / rev : null,
        pin: isPinned(s.code) ? 1 : 0,
      }
    })
    .filter(function (r) {
      return r.rev || r.orders || r.margin
    })

  var subjects = []
  all.forEach(function (r) {
    if (r.subject && subjects.indexOf(r.subject) === -1) subjects.push(r.subject)
  })
  subjects.sort(function (a, b) {
    return a.localeCompare(b, 'ru')
  })

  var q = skuFilter.q.trim().toLowerCase()
  var rows = all.filter(function (r) {
    if (isPinned(r.code)) return true // закреплённые видны всегда
    if (skuFilter.subject && r.subject !== skuFilter.subject) return false
    if (
      q &&
      r.code.toLowerCase().indexOf(q) === -1 &&
      (r.subject || '').toLowerCase().indexOf(q) === -1
    )
      return false
    return true
  })

  var sum = {
    rev: 0,
    net: 0,
    orders: 0,
    comm: 0,
    log: 0,
    ads: 0,
    other: 0,
    cogs: 0,
    margin: 0,
    card: 0,
    gross: 0,
  }
  rows.forEach(function (r) {
    sum.rev += r.rev
    sum.net += r.net
    sum.orders += r.orders
    sum.comm += r.comm
    sum.log += r.log
    sum.ads += r.ads
    sum.other += r.other
    sum.cogs += r.cogs
    sum.margin += r.margin
    sum.card += (r.card || 0) * r.net
    sum.gross += (r.gross || 0) * r.net
  })

  var cols = [
    {
      key: 'code',
      name: 'Артикул',
      l: true,
      get: function (r) {
        var open = isExpanded(r.code),
          has = hasSizes(r.code, sizeAgg)
        return (
          '<span class="cellpin">' +
          (has
            ? '<button class="expbtn" data-exp="' +
              esc(r.code) +
              '" type="button"' +
              ' aria-expanded="' +
              (open ? 'true' : 'false') +
              '" title="' +
              (open ? 'Свернуть размеры' : 'Показать размеры') +
              '">' +
              ICO_TRI +
              '</button>'
            : '<span class="expbtn empty"></span>') +
          '<button class="pinbtn' +
          (r.pin ? ' on' : '') +
          '" data-pin="' +
          esc(r.code) +
          '" type="button" aria-pressed="' +
          (r.pin ? 'true' : 'false') +
          '" title="' +
          (r.pin ? 'Открепить' : 'Закрепить наверху') +
          '">' +
          (r.pin ? ICO_PIN_ON : ICO_PIN_OFF) +
          '</button><span class="code">' +
          esc(r.code) +
          '</span></span>'
        )
      },
    },
    {
      key: 'subject',
      name: 'Предмет',
      l: true,
      get: function (r) {
        return '<span class="muted">' + esc(r.subject) + '</span>'
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
      key: 'net',
      name: 'Продано',
      get: function (r) {
        return nf0.format(r.net)
      },
    },
    {
      key: 'buy',
      name: 'Выкуп',
      title: 'Продано / заказано за этот период',
      get: function (r) {
        return pct(r.buy)
      },
    },
    {
      key: 'card',
      name: 'Цена карточки',
      title: 'Ваша цена до СПП. Именно к ней привязана выплата WB',
      get: function (r) {
        return money(r.card)
      },
    },
    {
      key: 'gross',
      name: 'Цена реализации',
      title: 'Цифра WB: цена карточки минус СПП, скидка за счёт WB',
      get: function (r) {
        return money(r.gross)
      },
    },
    {
      key: 'spp',
      name: 'СПП',
      title: 'Насколько WB опустил цену от вашей — на ваши деньги это не влияет',
      get: function (r) {
        return pct(r.spp)
      },
    },
    {
      key: 'rev',
      name: 'Выручка',
      sort: true,
      get: function (r) {
        return money(r.rev)
      },
    },
    {
      key: 'comm',
      name: 'Комиссия',
      get: function (r) {
        return money(-r.comm)
      },
    },
    {
      key: 'log',
      name: 'Логистика',
      get: function (r) {
        return money(-r.log)
      },
    },
    {
      key: 'logpct',
      name: 'Доля логистики',
      title: 'Логистика в процентах от выручки по выбранной базе',
      get: function (r) {
        return pct(r.logpct)
      },
      cls: function (r) {
        return r.logpct == null ? '' : r.logpct > 0.25 ? 'neg' : r.logpct < 0.12 ? 'pos' : ''
      },
    },
    {
      key: 'logo',
      name: 'Лог/заказ',
      title: 'Логистика на один заказ, а не на продажу',
      get: function (r) {
        return money(r.logo)
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
      key: 'drr',
      name: 'ДРР',
      title: 'Доля рекламы в выручке по выбранной базе',
      get: function (r) {
        return pct(r.drr)
      },
      cls: function (r) {
        return r.drr > 0.2 ? 'neg' : r.drr != null && r.drr < 0.05 ? 'pos' : ''
      },
    },
    {
      key: 'other',
      name: 'Прочее WB',
      get: function (r) {
        return money(-r.other)
      },
    },
    {
      key: 'cogs',
      name: 'Себест.',
      get: function (r) {
        return money(-r.cogs)
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
    {
      key: 'mpct',
      name: 'Маржа %',
      get: function (r) {
        return pct(r.mpct)
      },
      cls: function (r) {
        return r.mpct < 0 ? 'neg' : r.mpct > 0.4 ? 'pos' : ''
      },
    },
    {
      key: 'roi',
      name: 'ROI товара',
      title:
        'Маржа к себестоимости. По этой цифре планируют производство: она показывает, как отбивается партия',
      get: function (r) {
        return r.roi == null ? '—' : pct(r.roi, 0)
      },
      cls: function (r) {
        return r.roi == null ? '' : r.roi < 1 ? 'neg' : r.roi >= 2 ? 'pos' : ''
      },
    },
  ]
  var foot = {
    code: 'Показано ' + rows.length + ' из ' + all.length,
    roi: sum.cogs > 0 ? pct(sum.margin / sum.cogs, 0) : '—',
    logpct: pct(sum.rev ? sum.log / sum.rev : null),
    orders: nf0.format(sum.orders),
    net: nf0.format(sum.net),
    buy: pct(sum.orders ? sum.net / sum.orders : null),
    card: money(sum.net ? sum.card / sum.net : null),
    gross: money(sum.net ? sum.gross / sum.net : null),
    spp: pct(sum.card ? 1 - sum.gross / sum.card : null),
    rev: money(sum.rev),
    comm: money(-sum.comm),
    log: money(-sum.log),
    logo: money(sum.orders ? sum.log / sum.orders : null),
    ads: money(-sum.ads),
    drr: pct(sum.rev ? sum.ads / sum.rev : null),
    other: money(-sum.other),
    cogs: money(-sum.cogs),
    margin: money(sum.margin),
    mpct: pct(sum.rev ? sum.margin / sum.rev : null),
  }

  var h =
    '<div class="stack"><div><div class="sec"><h2>Что принёс каждый артикул</h2>' +
    '<p>За выбранный период, по дате расчёта WB, выручка по ' +
    baseName() +
    '. ' +
    'Реклама и часть удержаний приходят от WB без артикула — разнесены по долям фактической ' +
    'открутки. Клик по заголовку сортирует, звезда закрепляет артикул наверху, ' +
    'треугольник слева раскрывает размеры с их деньгами.</p></div>' +
    '<div class="filterbar">' +
    '<input type="search" id="skuQ" placeholder="Поиск по артикулу или предмету" ' +
    'value="' +
    esc(skuFilter.q) +
    '" aria-label="Поиск по артикулу">' +
    '<select id="skuSubj" aria-label="Фильтр по предмету"><option value="">Все предметы</option>' +
    subjects
      .map(function (x) {
        return (
          '<option value="' +
          esc(x) +
          '"' +
          (skuFilter.subject === x ? ' selected' : '') +
          '>' +
          esc(x) +
          '</option>'
        )
      })
      .join('') +
    '</select>'
  if (S.pinned.length) {
    h +=
      '<span class="pinnote">Закреплено: ' +
      S.pinned.length +
      ' <button class="btn" id="unpinAll" type="button">снять все</button></span>'
  }
  if (q || skuFilter.subject) {
    h += '<button class="btn" id="skuClear" type="button">Сбросить фильтр</button>'
  }
  h +=
    '</div><div id="t-sku"></div></div>' +
    '<div class="grid2">' +
    '<div class="note"><b>Три доли, которые стоит читать вместе.</b> «Доля логистики» показывает, сколько выручки съедают поездки — при выкупе около 27 % это самая тяжёлая статья. «ДРР» — то же про рекламу. «ROI товара» — маржа к себестоимости: по ней планируют производство, потому что она показывает, как отобьётся партия в 500 штук.</div>' +
    '<div class="note"><b>Какую цену считать своей.</b> Выплата WB жёстко привязана к цене ' +
    'карточки — 73.2 % от неё с разбросом 0.6 п.п. по всем артикулам. От цены реализации ' +
    'та же выплата гуляет от 76.8 до 92.9 %. Значит СПП — скидка за счёт WB, и как база ' +
    'для процентов цена реализации врёт. Переключатель базы — вверху страницы.</div>' +
    '</div></div>'
  el.innerHTML = h
  table($('t-sku'), 'sku', cols, rows, foot, {
    id: function (r) {
      return r.code
    },
    isOpen: function (r) {
      return isExpanded(r.code)
    },
    setOpen: function (code, on) {
      var i = expandedSkus.indexOf(code)
      if (on && i === -1) expandedSkus.push(code)
      if (!on && i !== -1) expandedSkus.splice(i, 1)
    },
    render: function (r) {
      return sizeTable(r.sku, agg[r.sku.nm_id] || {}, sizeAgg[r.sku.nm_id])
    },
  })

  var qi = $('skuQ')
  qi.addEventListener('input', function () {
    skuFilter.q = qi.value
    var pos = qi.selectionStart
    render()
    var again = $('skuQ')
    if (again) {
      again.focus()
      try {
        again.setSelectionRange(pos, pos)
      } catch {
        /* noop */
      }
    }
  })
  $('skuSubj').addEventListener('change', function () {
    skuFilter.subject = this.value
    render()
  })
  if ($('skuClear'))
    $('skuClear').addEventListener('click', function () {
      skuFilter = { q: '', subject: '' }
      render()
    })
  if ($('unpinAll'))
    $('unpinAll').addEventListener('click', function () {
      S.pinned = []
      persist()
      render()
    })
  el.querySelectorAll('button[data-pin]').forEach(function (b) {
    b.addEventListener('click', function () {
      togglePin(b.dataset.pin)
    })
  })
}
