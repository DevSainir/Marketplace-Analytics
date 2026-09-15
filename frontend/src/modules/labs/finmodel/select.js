/**
 * Выборки по датапаку и юнит-экономика: срезы P&L, посуточная симуляция
 * склада и всё, что из них выводится.
 */
import { addDays } from '@/modules/labs/finmodel/format'
import { DAYS_IN_MONTH, DP, S } from '@/modules/labs/finmodel/state'

/* ── выборки ────────────────────────────────────────────────────── */
var PC = {},
  OC = {},
  ZC = {}
export function indexCols() {
  DP.pnl_daily_cols.forEach(function (c, i) {
    PC[c] = i
  })
  DP.orders_daily_cols.forEach(function (c, i) {
    OC[c] = i
  })
  ;(DP.size_daily_cols || []).forEach(function (c, i) {
    ZC[c] = i
  })
}

var MONEY_KEYS = ['revenue', 'card', 'commission', 'logistics', 'ads', 'other_wb', 'cogs', 'margin']
var UNIT_KEYS = ['sold', 'returned', 'net_units', 'legs_fwd', 'legs_ret']

/** Сводит P&L и заказы по артикулам за выбранный период. */
export function slice(from, to) {
  var by = {}
  function bucket(nm) {
    if (!by[nm]) {
      by[nm] = { nm_id: nm, orders: 0, ad_spend: 0 }
      MONEY_KEYS.concat(UNIT_KEYS).forEach(function (k) {
        by[nm][k] = 0
      })
    }
    return by[nm]
  }
  DP.pnl_daily.forEach(function (r) {
    if (r[PC.d] < from || r[PC.d] > to) return
    var b = bucket(r[PC.nm_id])
    MONEY_KEYS.concat(UNIT_KEYS).forEach(function (k) {
      b[k] += r[PC[k]]
    })
  })
  DP.orders_daily.forEach(function (r) {
    if (r[OC.d] < from || r[OC.d] > to) return
    var b = bucket(r[OC.nm_id])
    b.orders += r[OC.orders]
    b.ad_spend += r[OC.ad_spend]
  })
  return by
}

var SIZE_KEYS = [
  'sold',
  'returned',
  'net_units',
  'revenue',
  'card',
  'commission',
  'logistics',
  'other_wb',
  'payout',
  'legs_fwd',
  'legs_ret',
]

/** P&L по размерам за период: { nm_id: { размер: сводка } }.
    Всё, кроме рекламы и себестоимости, здесь измерено — WB отдаёт эти строки
    с баркодом и размером, и сумма по размерам сходится с артикулом до копейки. */
export function sliceSizes(from, to) {
  var by = {},
    names = DP.size_names || []
  ;(DP.size_daily || []).forEach(function (r) {
    if (r[ZC.d] < from || r[ZC.d] > to) return
    var nm = r[ZC.nm_id],
      size = names[r[ZC.size]]
    var g = by[nm] || (by[nm] = {})
    var b = g[size]
    if (!b) {
      b = g[size] = { size: size }
      SIZE_KEYS.forEach(function (k) {
        b[k] = 0
      })
    }
    SIZE_KEYS.forEach(function (k) {
      b[k] += r[ZC[k]]
    })
  })
  return by
}

/** Ряды по дням за период — для графиков. */
export function daily(from, to) {
  var m = {}
  function at(d) {
    if (!m[d]) m[d] = { d: d, revenue: 0, card: 0, margin: 0, orders: 0, ads: 0, units: 0 }
    return m[d]
  }
  DP.pnl_daily.forEach(function (r) {
    if (r[PC.d] < from || r[PC.d] > to) return
    var x = at(r[PC.d])
    x.revenue += r[PC.revenue]
    x.card += r[PC.card]
    x.margin += r[PC.margin]
    x.units += r[PC.net_units]
  })
  DP.orders_daily.forEach(function (r) {
    if (r[OC.d] < from || r[OC.d] > to) return
    var x = at(r[OC.d])
    x.orders += r[OC.orders]
    x.ads += r[OC.ad_spend]
  })
  return Object.keys(m)
    .sort()
    .map(function (k) {
      return m[k]
    })
}

/** Выручка по выбранной базе. Цена реализации — цифра WB, в ней уже вычтена
    СПП; цена карточки — ваша цена до СПП, и именно к ней жёстко привязана
    выплата (73.2 % с разбросом 0.6 п.п. против 85.9 % с разбросом 4.5). */
export function revOf(a) {
  if (!a) return 0
  return S.revBase === 'card' ? a.card || 0 : a.revenue || 0
}
export function baseName() {
  return S.revBase === 'card' ? 'цене карточки' : 'цене реализации WB'
}

export function fixedPerDay() {
  var f = S.fixed,
    sum = 0
  Object.keys(f).forEach(function (k) {
    sum += Number(f[k]) || 0
  })
  return sum / DAYS_IN_MONTH
}

/** Юнит-экономика артикула за выбранный период, с откатом на всё окно. */
export function econ(sku, agg) {
  var a = agg[sku.nm_id],
    h = sku.hist
  var useSlice = a && a.net_units > 0 && a.orders > 0 && a.revenue > 0
  var src = useSlice
    ? a
    : {
        revenue: h.revenue,
        card: h.card,
        commission: h.commission,
        logistics: h.logistics,
        ads: h.ads,
        other_wb: h.other_wb,
        cogs: h.cogs,
        margin: h.margin,
        net_units: h.net_units,
        orders: h.orders,
      }
  if (!(src.net_units > 0) || !(src.orders > 0)) return null
  var base = revOf(src)
  if (!(base > 0)) return null
  // Выплата WB выводится из маржи: маржа = выплата − логистика − прочее − реклама −
  // себестоимость. Тогда «удержания из цены» = база − выплата, и абсолютная маржа
  // не зависит от того, какую базу выручки выбрали, — меняются только проценты.
  var payout = src.margin + src.logistics + src.other_wb + src.ads + src.cogs
  return {
    fromSlice: useSlice,
    cheque: base / src.net_units,
    commRate: (base - payout) / base,
    logPerOrder: src.logistics / src.orders,
    adsPerOrder: src.ads / src.orders,
    otherPerOrder: src.other_wb / src.orders,
    cogsPerUnit: sku.cost > 0 ? sku.cost : src.cogs / src.net_units,
  }
}

export function buyoutOf(sku) {
  var o = S.buyout[sku.code]
  if (o != null && isFinite(o) && o > 0) return o
  return sku.buyout || 0
}
export function growthOf(sku) {
  var g = S.growth[sku.code]
  return g != null && isFinite(g) ? Number(g) : 0
}
export function baseOrders(sku) {
  if (S.scenario === 'peak') {
    var p = sku.peak || {}
    if (p.peak_orders != null) return p.peak_orders
  }
  return sku.base_orders_per_day || 0
}

/**
 * Посуточная симуляция одного артикула. Заказы растут по индивидуальному
 * недельному коэффициенту; выкуп списывает товар со склада WB + FBS;
 * когда склад кончился, продажи прекращаются (если включено ограничение).
 */
/** Поправка выкупа на ноябрь–декабрь. Подъёма спроса в данных нет — заказы
    идут за рекламой, — а вот выкуп в пик проседает: измерено на фиксированной
    корзине артикулов внутри одного непрерывного отрезка истории. */
export function seasonFactor(iso) {
  var sn = (DP.monitoring || {}).season || {}
  if (!S.season || !sn.available) return 1
  var mm = iso.slice(5, 7)
  return sn.peak_months.indexOf(mm) !== -1 ? sn.factor : 1
}

export function simulate(sku, days, e) {
  var stock = sku.stock.available
  var b = buyoutOf(sku),
    g = growthOf(sku) / 100,
    base = baseOrders(sku)
  var out = [],
    oosDay = null
  for (var i = 0; i < days; i++) {
    var ord = base * Math.pow(1 + g, i / 7)
    var want = ord * b * seasonFactor(addDays(DP.meta.stock_asof, i))
    var sold = S.limitByStock ? Math.min(want, Math.max(stock, 0)) : want
    if (S.limitByStock) {
      // логистика и реклама платятся за заказ, а не за продажу: если склад
      // пуст, заказов тоже нет — карточка выпадает из выдачи
      if (stock <= 0) {
        ord = 0
        sold = 0
      }
      stock -= sold
      if (stock <= 0 && oosDay === null) oosDay = i
    } else if (stock > 0) {
      stock -= sold
      if (stock <= 0 && oosDay === null) oosDay = i
    }
    var rev = sold * e.cheque
    var ads = ord * e.adsPerOrder * S.adMult
    var cost =
      rev * e.commRate + ord * e.logPerOrder + ads + ord * e.otherPerOrder + sold * e.cogsPerUnit
    out.push({
      orders: ord,
      sales: sold,
      revenue: rev,
      ads: ads,
      margin: rev - cost,
      cogs: sold * e.cogsPerUnit,
      stock: Math.max(stock, 0),
    })
  }
  return { days: out, oosDay: oosDay }
}

/** Дни до нуля по остаткам — та же механика, но без денег. */
export function daysToZero(sku, extraStock) {
  var stock = sku.stock.available + (extraStock || 0)
  var b = buyoutOf(sku),
    g = growthOf(sku) / 100,
    base = baseOrders(sku)
  if (!(base > 0) || !(b > 0)) return null
  if (stock <= 0) return 0
  for (var i = 0; i < 400; i++) {
    stock -= base * Math.pow(1 + g, i / 7) * b * seasonFactor(addDays(DP.meta.stock_asof, i))
    if (stock <= 0) return i + 1
  }
  return null
}
