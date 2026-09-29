/**
 * Где проходят рамки «хорошо / плохо» в отчёте по артикулам.
 *
 * Цвет в таблице — не украшение, а фильтр внимания: в отчёте на сорок строк и
 * двадцать колонок глаз без подсказки читает первые три строки. Поэтому
 * подсвечена только та цифра, которая вышла за рамку, а всё, что лежит внутри
 * обычного разброса, остаётся обычным текстом — если подкрасить половину
 * таблицы, не выделено ничего.
 *
 * Рамки взяты по фактическому распределению кабинета «Демо» (окна 30 / 90 /
 * 365 дней, 30–40 артикулов с продажами), а не выдуманы: красная граница стоит
 * примерно на верхнем дециле, зелёная — примерно на нижнем квартиле, так что в
 * типичном отчёте подсвечено несколько строк, а не всё подряд. Замеренные
 * квартили на 90 днях, для сверки при следующей правке:
 *
 *   Возвраты %        p25 10,4   медиана 12,6   p75 16,1   max 27,8
 *   Доля логистики    p25 19,8   медиана 29,2   p75 34,1   max 70,4
 *   ДРР               p25  0,0   медиана  0,0   p75  7,9   max 26,0
 *   Маржа %           p25 12,2   медиана 31,3   p75 38,8   min −24,2
 *   ROI               p25   38   медиана  120   p75  178   min −54
 *   Выкуп %           p25 22,3   медиана 30,4   p75 35,2
 *
 * СПП сознательно не подсвечивается: это скидка за счёт WB, на деньги продавца
 * она не влияет, и «хорошей» или «плохой» стороны у неё нет.
 */

/**
 * Рамки по метрикам. `good`/`bad` — пороги в тех же единицах, в которых
 * приходит значение (проценты как 12.6, а не 0.126). `higherIsBetter` говорит,
 * с какой стороны рамки лежит плохое.
 */
export const BOUNDS = {
  /** Возвраты: доля выкупленного, что вернули. Меньше — лучше. */
  returnPct: { good: 8, bad: 20, higherIsBetter: false },
  /** Доля логистики в выручке — самая тяжёлая статья при низком выкупе. */
  logisticsPct: { good: 20, bad: 35, higherIsBetter: false },
  /**
   * ДРР — доля рекламы в выручке. `zeroIsAbsent`: ноль здесь почти всегда
   * значит «рекламу не крутили», а не «крутили идеально дёшево», и зелёный на
   * нём красит половину отчёта за то, чего не делали.
   */
  advertisingPct: { good: 5, bad: 20, higherIsBetter: false, zeroIsAbsent: true },
  /** Маржа % — чистая прибыль к выручке. Ноль это уже плохо. */
  profitPct: { good: 40, bad: 0, higherIsBetter: true },
  /** ROI товара: ниже 100 % партия не отбивается. */
  roi: { good: 200, bad: 100, higherIsBetter: true },
  /** Выкуп артикула и размера: продано к доехавшим до покупателя. */
  buyoutPct: { good: 35, bad: 20, higherIsBetter: true },
}

/**
 * Куда попало значение: `'positive'`, `'negative'` или `''` (внутри рамок).
 *
 * @param {string} metric Ключ из {@link BOUNDS}.
 * @param {number|string|null|undefined} value
 * @returns {'positive'|'negative'|''}
 */
export function tone(metric, value) {
  const bounds = BOUNDS[metric]
  if (!bounds || value === null || value === undefined || value === '') return ''
  const n = Number(value)
  if (!Number.isFinite(n)) return ''
  if (bounds.zeroIsAbsent && n === 0) return ''
  if (bounds.higherIsBetter) {
    if (n < bounds.bad) return 'negative'
    return n >= bounds.good ? 'positive' : ''
  }
  if (n > bounds.bad) return 'negative'
  return n <= bounds.good ? 'positive' : ''
}

/** Класс текста для той же проверки — то, что вешается на ячейку. */
export function toneClass(metric, value) {
  const t = tone(metric, value)
  if (t === 'positive') return 'text-status-positive'
  if (t === 'negative') return 'text-status-negative'
  return ''
}

/**
 * Деньги: подсвечиваем только минус. Рамки у суммы нет — «много» зависит от
 * масштаба артикула, а вот убыток плох при любом масштабе.
 *
 * @param {number|string|null|undefined} value
 */
export function amountClass(value) {
  if (value === null || value === undefined || value === '') return ''
  return Number(value) < 0 ? 'text-status-negative' : ''
}
