/**
 * Turning a test's log of turns into the geometry the timeline draws.
 *
 * Pure functions, in their own file, because this is the part that is worth
 * asserting: a bar is a claim about proportions, and a proportion is exactly
 * the kind of thing that looks plausible while being wrong. The component
 * renders what comes out of here and owns nothing else about it.
 *
 * Two properties the geometry has to keep, both learned from what a naive
 * `duration / total * 100` produces:
 *
 * * **Every turn is visible.** A photo that stood nine minutes inside a
 *   four-day test is 0.15 % of the track — a segment nobody can hover and a
 *   divider nobody can see. Segments get a floor, and the rest is rescaled so
 *   the widths still sum to the whole track. That makes a very short turn
 *   *wider* than its share, which is the right trade: the number in the popup
 *   is the truth, and the bar is the index into it. The floor **shrinks as the
 *   line fills up**, because a fixed one stops being a floor and becomes the
 *   layout: ten photos over ten laps is a hundred turns, and a hundred 1.5 %
 *   minimums would make every turn the same width whatever it did.
 * * **The line ends where the rotation did.** The last exposure of a stopped
 *   test has no `deactivated_at` — a pause leaves the photo on the card — so
 *   measuring it to «сейчас» drew a segment that grew all weekend and squeezed
 *   every real turn into the left edge. The caller passes `endsAt`, which is
 *   the stop for a stopped test and the clock only for a live one.
 */

/** Smallest share of the track one turn may occupy, in percent. */
const MIN_SEGMENT_PERCENT = 1.5

/** …but the floors together may never claim more than this much of the track. */
const MAX_FLOOR_SHARE_PERCENT = 50

/**
 * Build one timeline out of a test's exposures.
 *
 * @param {Array<object>} history Exposure rows as the detail endpoint returns
 *   them — newest first, `deactivated_at` null on the open one.
 * @param {{endsAt?: number, round?: number}} [options] `endsAt` is where the
 *   line stops — the reader's clock for a live test, the moment it stopped for
 *   any other; `round` restricts the line to one lap, 0 for all.
 * @returns {{segments: Array<object>, startMs: number|null, endMs: number|null,
 *   totalMs: number, live: boolean}} Geometry, oldest turn first.
 */
export function buildTimeline(history, { endsAt = Date.now(), round = 0 } = {}) {
  const rows = (history ?? [])
    .filter((row) => !round || row.round_number === round)
    .map((row) => toTurn(row, endsAt))
    .filter((turn) => turn !== null)
    // The log arrives newest first; a timeline reads left to right.
    .sort((a, b) => a.startMs - b.startMs)

  if (!rows.length) return { segments: [], startMs: null, endMs: null, totalMs: 0, live: false }

  const startMs = rows[0].startMs
  const endMs = Math.max(...rows.map((turn) => turn.endMs))
  const spanMs = Math.max(1, endMs - startMs)

  const floor = Math.min(MIN_SEGMENT_PERCENT, MAX_FLOOR_SHARE_PERCENT / rows.length)
  const raw = rows.map((turn) => Math.max(floor, (turn.durationMs / spanMs) * 100))
  const scale = 100 / raw.reduce((sum, width) => sum + width, 0)

  let left = 0
  const segments = rows.map((turn, index) => {
    const widthPercent = raw[index] * scale
    // Every turn is labelled, and they alternate above and below the track to
    // halve how close two thumbnails can come. Dropping the crowded ones was
    // tried first: what it actually hid was the short turns, which are the ones
    // worth looking at.
    //
    // The FIRST one goes below. Above, it stands directly under the stamp that
    // says when the line begins and pushes it up off the track; below, the two
    // ends of the line sit level with each other, which is what they are.
    const segment = { ...turn, leftPercent: left, widthPercent, above: index % 2 === 1 }
    left += widthPercent
    return segment
  })

  return {
    segments,
    startMs,
    endMs,
    totalMs: endMs - startMs,
    live: rows.some((turn) => turn.open),
  }
}

/**
 * One exposure row as the timeline needs it, or `null` if it has no clock.
 *
 * @param {object} row An exposure row.
 * @param {number} endsAt Where an unfinished turn is cut off.
 * @returns {object|null} The turn, or `null` when `activated_at` is unusable.
 */
function toTurn(row, endsAt) {
  const startMs = Date.parse(row.activated_at ?? '')
  if (Number.isNaN(startMs)) return null

  const closed = Date.parse(row.deactivated_at ?? '')
  const open = Number.isNaN(closed)
  // Clamped at the start: a stop recorded a moment before the last install —
  // or a browser clock behind the server's — would otherwise give the turn a
  // negative width.
  const endMs = open ? Math.max(startMs, endsAt) : closed

  return {
    key: `${row.variant_id}-${row.activated_at}`,
    variantId: row.variant_id,
    label: row.is_original ? 'Главное' : `Вариант ${row.position}`,
    round: row.round_number,
    startMs,
    endMs,
    durationMs: Math.max(0, endMs - startMs),
    open,
    views: Number(row.views ?? 0),
    clicks: Number(row.clicks ?? 0),
    clickThrough: row.click_through ?? null,
  }
}

/**
 * The laps a test has served, newest first — the options of the loop picker.
 *
 * Read off the exposures rather than off `rounds_completed`: the log is what
 * the timeline draws, and a picker offering a lap with no turns in it would
 * select an empty line.
 *
 * @param {Array<object>} history Exposure rows.
 * @returns {Array<number>} Round numbers, highest first.
 */
export function roundsIn(history) {
  const seen = new Set((history ?? []).map((row) => row.round_number).filter(Boolean))
  return [...seen].sort((a, b) => b - a)
}

/**
 * «08.09» and «12:05 МСК», as two parts.
 *
 * Moscow, spelled out, because WB operates in Moscow time and the seller reads
 * these next to figures from the WB cabinet — the same rule «История действий»
 * follows. Two parts because the ends of the track are where the block is
 * narrowest: one such stamp on one line is the width of two thumbnails.
 *
 * @param {number|null} ms Epoch milliseconds.
 * @returns {{date: string, time: string}} The two parts, or «—» and «».
 */
export function formatStamp(ms) {
  if (ms === null || ms === undefined) return { date: '—', time: '' }
  const at = new Date(ms)
  const zone = { timeZone: 'Europe/Moscow' }
  return {
    date: at.toLocaleString('ru-RU', { ...zone, day: '2-digit', month: '2-digit' }),
    time: `${at.toLocaleString('ru-RU', { ...zone, hour: '2-digit', minute: '2-digit' })} МСК`,
  }
}

/**
 * `Хч Ym`, or minutes alone under an hour — a lap may run for days.
 *
 * @param {number} ms A span in milliseconds.
 * @returns {string} The span in words.
 */
export function formatDuration(ms) {
  const minutes = Math.round(Math.max(0, ms ?? 0) / 60_000)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)
  if (days) return `${days} д ${hours % 24} ч`
  if (hours) return `${hours} ч ${minutes % 60} мин`
  return `${minutes} мин`
}
