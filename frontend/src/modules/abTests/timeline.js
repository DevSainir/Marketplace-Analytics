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
 *   is the truth, and the bar is the index into it.
 * * **The open turn ends at «сейчас».** The last exposure of a live test has no
 *   `deactivated_at`, and a segment of zero width would say the rotation had
 *   stopped. The caller passes the clock in rather than this reading it, so a
 *   test rendered twice a second apart is not a different picture each time.
 */

/** Smallest share of the track one turn may occupy, in percent. */
const MIN_SEGMENT_PERCENT = 1.5

/** A label (thumbnail + title) needs this much clear track to its left. */
const LABEL_CLEARANCE_PERCENT = 7

/**
 * Build one timeline out of a test's exposures.
 *
 * @param {Array<object>} history Exposure rows as the detail endpoint returns
 *   them — newest first, `deactivated_at` null on the open one.
 * @param {{now?: number, round?: number}} [options] `now` is the clock the open
 *   turn is measured to; `round` restricts the line to one lap, 0 for all.
 * @returns {{segments: Array<object>, startMs: number|null, endMs: number|null,
 *   totalMs: number, live: boolean}} Geometry, oldest turn first.
 */
export function buildTimeline(history, { now = Date.now(), round = 0 } = {}) {
  const rows = (history ?? [])
    .filter((row) => !round || row.round_number === round)
    .map((row) => toTurn(row, now))
    .filter((turn) => turn !== null)
    // The log arrives newest first; a timeline reads left to right.
    .sort((a, b) => a.startMs - b.startMs)

  if (!rows.length) return { segments: [], startMs: null, endMs: null, totalMs: 0, live: false }

  const startMs = rows[0].startMs
  const endMs = Math.max(...rows.map((turn) => turn.endMs))
  const spanMs = Math.max(1, endMs - startMs)

  const raw = rows.map((turn) => Math.max(MIN_SEGMENT_PERCENT, (turn.durationMs / spanMs) * 100))
  const scale = 100 / raw.reduce((sum, width) => sum + width, 0)

  let left = 0
  let lastLabelAt = -Infinity
  const segments = rows.map((turn, index) => {
    const widthPercent = raw[index] * scale
    // A label is dropped rather than squeezed: two thumbnails overlapping is
    // worse than one turn going unlabelled, and the popup names every turn.
    const labelled = left - lastLabelAt >= LABEL_CLEARANCE_PERCENT
    if (labelled) lastLabelAt = left
    const segment = { ...turn, leftPercent: left, widthPercent, labelled }
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
 * @param {number} now The reader's clock, for the turn still in progress.
 * @returns {object|null} The turn, or `null` when `activated_at` is unusable.
 */
function toTurn(row, now) {
  const startMs = Date.parse(row.activated_at ?? '')
  if (Number.isNaN(startMs)) return null

  const closed = Date.parse(row.deactivated_at ?? '')
  const open = Number.isNaN(closed)
  // Clamped at the start: a browser clock behind the server's would otherwise
  // give the live turn a negative width.
  const endMs = open ? Math.max(startMs, now) : closed

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
