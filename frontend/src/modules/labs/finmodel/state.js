/**
 * Датапак и пользовательские допущения. Допущения живут в localStorage:
 * это страница-песочница, у неё нет ни своего API, ни места в базе.
 */
import { $ } from '@/modules/labs/finmodel/dom'

/** Средняя длина месяца: постоянные расходы заданы за месяц, а считаются в днях. */
export const DAYS_IN_MONTH = 30.44

/** Датапак и текущие допущения. Обе ссылки переприсваиваются на старте. */
export let DP = null
export let S = null

/** Принять датапак — до этого ни одна выборка не имеет смысла. */
export function setDP(data) {
  DP = data
}

/** Собрать допущения: значения по умолчанию поверх сохранённых в браузере. */
export function initAssumptions() {
  S = defaults()
  merge(loadLocal())
}

export function defaults() {
  var fb = DP.fixed_from_bank,
    m = DAYS_IN_MONTH / fb.days
  return {
    from: DP.meta.pnl_from,
    to: DP.meta.pnl_to,
    tab: 'sum',
    scenario: 'base',
    horizon: 8,
    adMult: 1,
    limitByStock: true,
    season: true,
    revBase: 'gross', // gross — цена реализации WB, card — цена карточки
    parBy: 'margin', // чем сортировать блок «кто генерит»: margin | revenue
    parGroup: 'sku', // разрез блока: sku | subject | brand
    pinned: [],
    growth: {}, // артикул -> % роста заказов в неделю
    buyout: {}, // артикул -> переопределённый выкуп, доля
    fixed: {
      taxes: Math.round(fb.taxes * m),
      insurance: Math.round(fb.insurance * m),
      bank: Math.round(fb.bank_fees * m),
      salary: 0,
      rent: 0,
      other: 0,
    },
  }
}

export function loadLocal() {
  try {
    return JSON.parse(localStorage.getItem('finmodel.v1') || 'null')
  } catch {
    return null
  }
}
export function persist() {
  var body = {
    scenario: S.scenario,
    horizon: S.horizon,
    adMult: S.adMult,
    limitByStock: S.limitByStock,
    revBase: S.revBase,
    pinned: S.pinned,
    season: S.season,
    parBy: S.parBy,
    parGroup: S.parGroup,
    growth: S.growth,
    buyout: S.buyout,
    fixed: S.fixed,
  }
  try {
    localStorage.setItem('finmodel.v1', JSON.stringify(body))
    setSaveState('допущения сохранены в этом браузере')
  } catch {
    setSaveState('допущения не сохраняются — приватное окно')
  }
}
export function setSaveState(t) {
  $('savestate').textContent = t
}
export function merge(body) {
  if (!body) return
  ;[
    'scenario',
    'horizon',
    'adMult',
    'limitByStock',
    'revBase',
    'season',
    'parBy',
    'parGroup',
  ].forEach(function (k) {
    if (body[k] !== undefined && body[k] !== null) S[k] = body[k]
  })
  ;['growth', 'buyout', 'fixed'].forEach(function (k) {
    if (body[k] && typeof body[k] === 'object') S[k] = Object.assign({}, S[k], body[k])
  })
  if (Array.isArray(body.pinned)) S.pinned = body.pinned.slice()
}
