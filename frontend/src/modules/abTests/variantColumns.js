/**
 * The result grid's data and wording, projected once and rendered twice.
 *
 * The desktop table and the narrow-screen pager show the same seven figures for
 * the same photos; only the axis they run along differs. Keeping the projection
 * here — rather than in whichever component was written first — is what stops
 * the two from disagreeing about which photo is the leader or how a gap is
 * coloured, which is the failure mode a second copy always eventually produces.
 *
 * See `VariantResultsTable.vue` for why each derived row exists.
 */

/**
 * How far behind the leader still counts as close.
 *
 * Thresholds rather than a gradient, because the column answers a yes/no
 * question — is this photo still a contender — and a gradient makes every value
 * look like a slightly different shade of the same answer. Ten percent is
 * inside the noise of a few thousand impressions; past thirty, no amount of
 * further data is going to rescue the photo.
 */
const CLOSE_ENOUGH = -10
const CLEARLY_BEHIND = -30

/** The rows of the grid, in the order they are read. */
export const METRICS = [
  { key: 'views', label: 'Показов', kind: 'count' },
  { key: 'clicks', label: 'Кликов', kind: 'count', hint: 'Переходы в карточку из выдачи' },
  { key: 'click_through', label: 'CTR', kind: 'percent', hint: 'Доля переходов в карточку' },
  {
    key: 'ctr_result',
    label: 'Результат',
    kind: 'result',
    hint: 'Насколько CTR отличается от лучшего, в процентах',
  },
  {
    key: 'ctr_gap',
    label: 'Отклонение CTR от лучшего',
    kind: 'gap',
    hint: 'Та же разница, но в процентных пунктах',
  },
  {
    key: 'rounds_won',
    label: 'Побед в раундах по CTR',
    kind: 'wins',
    hint: 'Считается по всему тесту, а не по выбранному кругу',
  },
  {
    key: 'rounds_played',
    label: 'Кругов',
    kind: 'count',
    hint: 'В скольких кругах фото участвовало. Считается по всему тесту',
  },
]

/**
 * The figures each photo shows — for the whole test, or for one lap.
 *
 * A lap is rebuilt from «История действий» rather than fetched: every turn
 * there already carries its lap, its photo and what it earned, so filtering is
 * arithmetic over data the page is holding. `rounds_won` and `rounds_played`
 * stay whole-test figures — they are properties of the test, and «побед в этом
 * круге» is one or nothing, which is not a figure worth showing.
 *
 * @param {object} test The test, as the detail endpoint returns it.
 * @param {number} round Lap to show, or 0 for the whole test.
 * @returns {Array<object>} One entry per photo, in rotation order.
 */
export function buildColumns(test, round) {
  const variants = test?.variants ?? []
  if (!round) return variants

  const byVariant = {}
  for (const turn of test.history ?? []) {
    if (turn.round_number !== round) continue
    const seen = byVariant[turn.variant_id] ?? { views: 0, clicks: 0 }
    byVariant[turn.variant_id] = {
      views: seen.views + turn.views,
      clicks: seen.clicks + turn.clicks,
    }
  }

  const lap = variants.map((variant) => {
    const counts = byVariant[variant.variant_id] ?? { views: 0, clicks: 0 }
    return {
      ...variant,
      views: counts.views,
      clicks: counts.clicks,
      click_through: counts.views ? (counts.clicks * 100) / counts.views : null,
    }
  })

  // The leader of this lap, so «Результат» compares within what is shown rather
  // than against a photo whose best hour was three laps ago.
  const best = Math.max(...lap.map((v) => v.click_through ?? -1))
  return lap.map((variant) => ({
    ...variant,
    ctr_gap: variant.click_through === null || best <= 0 ? null : best - variant.click_through,
    ctr_result:
      variant.click_through === null || best <= 0
        ? null
        : ((variant.click_through - best) * 100) / best,
  }))
}

/**
 * The best measured photo still in the rotation, or null.
 *
 * An excluded photo cannot lead a comparison it has left — its numbers stay on
 * the table as the record of why it was excluded, not as a bar for the others.
 *
 * @param {Array<object>} columns Projected photos.
 * @returns {string|null} The leading variant id.
 */
export function leaderOf(columns) {
  const measured = columns.filter((v) => v.click_through !== null && !v.is_excluded)
  if (!measured.length) return null
  return measured.reduce((a, b) => (b.click_through > a.click_through ? b : a)).variant_id
}

/** «Главное» for the captured photo, «Вариант N» for an upload. */
export function variantTitle(variant) {
  return variant.is_original ? 'Главное' : `Вариант ${variant.position}`
}

export function count(value) {
  return Number(value ?? 0).toLocaleString('ru-RU')
}

/**
 * A percentage in Russian: comma for the decimal mark, as the WB cabinet writes
 * it. `toFixed` gives a dot, which reads as a thousands separator here.
 */
export function percent(value, digits = 2) {
  if (value === null || value === undefined) return '—'
  return `${Number(value).toLocaleString('ru-RU', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}%`
}

/**
 * A whole percent, with no signed zero.
 *
 * `Math.round` is applied before the sign is read, so a photo 0.3 % behind
 * shows «0%» rather than «-0%» — a minus in front of a zero says the photo is
 * behind by an amount too small to print, which is not what a reader takes
 * from it.
 */
function wholePercent(value) {
  const rounded = Math.round(Number(value))
  return `${rounded === 0 ? 0 : rounded}%`
}

/** «раз» / «раза» — a Russian count does not take one plural form. */
function plural(n) {
  const tail = n % 100
  if (tail >= 11 && tail <= 14) return 'раз'
  return [2, 3, 4].includes(n % 10) ? 'раза' : 'раз'
}

/**
 * One figure: its text, and the class that says how to read it.
 *
 * @param {object} variant A projected photo.
 * @param {object} metric One entry of {@link METRICS}.
 * @param {{leaderId: string|null, bestWins: number}} context The comparison the
 *   figure is read against.
 * @returns {{text: string, class: string}}
 */
export function cellFor(variant, metric, { leaderId, bestWins }) {
  const value = variant[metric.key]

  if (metric.kind === 'count') return { text: count(value), class: '' }
  if (metric.kind === 'percent') return { text: percent(value), class: '' }

  if (metric.kind === 'result') {
    if (variant.variant_id === leaderId) {
      return { text: 'Лучший', class: 'text-status-positive font-semibold' }
    }
    if (value === null || value === undefined) return { text: '—', class: 'text-muted' }
    const gap = Number(value)
    return {
      text: wholePercent(gap),
      class:
        gap >= CLOSE_ENOUGH
          ? 'text-status-positive'
          : gap >= CLEARLY_BEHIND
            ? 'text-status-warning'
            : 'text-status-negative',
    }
  }

  if (metric.kind === 'gap') {
    if (variant.variant_id === leaderId) return { text: '0%', class: 'text-status-positive' }
    if (value === null || value === undefined) return { text: '—', class: 'text-muted' }
    return { text: `${percent(value)} ↓`, class: 'text-status-negative' }
  }

  const wins = Number(value ?? 0)
  return {
    text: `${count(wins)} ${plural(wins)}`,
    class:
      wins === 0
        ? 'text-status-negative'
        : wins === bestWins
          ? 'text-status-positive'
          : 'text-status-warning',
  }
}

/** The highest lap count any photo has won, for colouring «Побед». */
export function bestWinsOf(columns) {
  return Math.max(0, ...columns.map((v) => Number(v.rounds_won ?? 0)))
}
