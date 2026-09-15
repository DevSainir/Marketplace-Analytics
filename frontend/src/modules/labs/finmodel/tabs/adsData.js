/**
 * Срезы рекламы за период. Денег три источника, и они не равны: удержания WB
 * (факт списания, из них считается маржа), история затрат кабинета (точная
 * дата и тип ставки) и статистика кампаний (единственная, где есть зона
 * показа). За окно кабинет и статистика расходятся на 1.2 %, поэтому зона
 * берётся долей, а не суммой.
 */
import { css } from '@/modules/labs/finmodel/dom'
import { esc, money, num } from '@/modules/labs/finmodel/format'

export var KIND_BY_BID = { manual: 'Ручная Ставка', unified: 'Единая Ставка' }
export var adsView = { q: '', subject: '', brand: '', group: 'sku', all: false }
export var ADS_GROUPS = [
  { id: 'sku', name: 'Артикулы', col: 'Артикул', by: 'артикулам' },
  { id: 'subject', name: 'Предметы', col: 'Предмет', by: 'предметам' },
  { id: 'brand', name: 'Бренды', col: 'Бренд', by: 'брендам' },
]

/** Открутка кабинета за период: всего, с баланса, бонусами и по типам ставки. */
export function adsWindow(A, from, to) {
  var out = { total: 0, balance: 0, promo: 0, kinds: [] },
    by = {}
  ;(A.daily_kind || []).forEach(function (r) {
    var d = r[0]
    if (d < from || d > to) return
    var kind = r[1] || 'Без типа',
      src = r[2],
      amount = r[3]
    var k = by[kind] || (by[kind] = { name: kind, total: 0, balance: 0, promo: 0 })
    k.total += amount
    k[src] += amount
    out.total += amount
    out[src] += amount
  })
  out.kinds = Object.keys(by)
    .map(function (k) {
      return by[k]
    })
    .sort(function (a, b) {
      return b.total - a.total
    })
  return out
}

/** Доля поиска в открутке за период — по статистике кампаний, всего и по типу ставки. */
export function adsZones(A, from, to) {
  var out = { share: null, days: 0, byKind: {} },
    tot = [0, 0],
    by = {},
    days = {}
  ;(A.zones_daily || []).forEach(function (r) {
    var d = r[0]
    if (d < from || d > to) return
    days[d] = 1
    var kind = KIND_BY_BID[r[1]]
    tot[0] += r[2]
    tot[1] += r[3]
    if (!kind) return
    var b = by[kind] || (by[kind] = [0, 0])
    b[0] += r[2]
    b[1] += r[3]
  })
  out.days = Object.keys(days).length
  var sum = tot[0] + tot[1]
  if (!sum) return out
  out.share = tot[0] / sum
  Object.keys(by).forEach(function (k) {
    var s2 = by[k][0] + by[k][1]
    if (s2) out.byKind[k] = { search: by[k][0], rest: by[k][1], share: by[k][0] / s2 }
  })
  return out
}

/** Горизонтальные полосы с накоплением: доля первой части подписана внутри. */
export function stackBars(rows) {
  var colors = [css('--s1'), css('--s2')]
  return (
    '<div class="stacks">' +
    rows
      .map(function (r) {
        var sum = r.parts.reduce(function (a, b) {
          return a + b
        }, 0)
        if (!sum) return ''
        return (
          '<div class="stackrow"><div class="stacklab">' +
          esc(r.label) +
          '</div>' +
          '<div class="stackbar">' +
          r.parts
            .map(function (v, i) {
              var w = (v / sum) * 100
              return (
                '<span style="width:' +
                w.toFixed(2) +
                '%;background:' +
                colors[i % colors.length] +
                '" title="' +
                esc(money(v)) +
                ' · ' +
                num(w, 1) +
                ' %"></span>'
              )
            })
            .join('') +
          '</div>' +
          '<div class="stackval">' +
          money(r.parts[0]) +
          ' · ' +
          num((r.parts[0] / sum) * 100, 0) +
          ' %</div></div>'
        )
      })
      .join('') +
    '</div>'
  )
}

/* ── Реклама ────────────────────────────────────────────────────── */
