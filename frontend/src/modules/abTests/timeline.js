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
 *   measuring it to "now" drew a segment that grew all weekend and squeezed
 *   every real turn into the left edge. The caller passes `endsAt`, which is
 *   the stop for a stopped test and the clock only for a live one.
 */

import { formatMoscow } from '@/core/utils/moscow'

/** Smallest share of the track one turn may occupy, in percent. */
const MIN_SEGMENT_PERCENT = 1.5

/** …but the floors together may never claim more than this much of the track. */
const MAX_FLOOR_SHARE_PERCENT = 50

/**
 * Build one timeline out of a test's exposures.
 *
 * @param {Array<object>} history Exposure rows as the detail endpoint returns
 *   them — newest first, `deactivated_at` null on the open one.
 * @param {{endsAt?: number, round?: number, campaignId?: number}} [options]
 *   `endsAt` is where the line stops — the reader's clock for a live test, the
 *   moment it stopped for any other; `round` restricts the line to one lap, 0
 *   for all; `campaignId` restricts it to the turns ONE campaign measured, 0
 *   for all of them.
 * @returns {{segments: Array<object>, startMs: number|null, endMs: number|null,
 *   totalMs: number, live: boolean}} Geometry, oldest turn first.
 */
export function buildTimeline(history, { endsAt = Date.now(), round = 0, campaignId = 0 } = {}) {
  const rows = (history ?? [])
    .filter((row) => !round || row.round_number === round)
    .filter((row) => !campaignId || sliceOf(row, campaignId) !== null)
    .map((row) => toTurn(row, endsAt, campaignId))
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
 * What one campaign measured in one turn, or `null` if it measured nothing.
 *
 * Nothing is not zero: a campaign switched off on the fourth lap did not run
 * the fifth, and drawing it as a turn with no traffic says the opposite.
 *
 * @param {object} row An exposure row.
 * @param {number} campaignId The campaign.
 * @returns {object|null} That campaign's entry for the turn.
 */
function sliceOf(row, campaignId) {
  return (row.campaigns ?? []).find((entry) => entry.campaign_id === campaignId) ?? null
}

/**
 * One exposure row as the timeline needs it, or `null` if it has no clock.
 *
 * @param {object} row An exposure row.
 * @param {number} endsAt Where an unfinished turn is cut off.
 * @param {number} [campaignId] Read the counts through one campaign, or 0 for
 *   the turn's own totals. The CLOCK is never filtered — the photo stood for as
 *   long as it stood whoever was paying.
 * @returns {object|null} The turn, or `null` when `activated_at` is unusable.
 */
function toTurn(row, endsAt, campaignId = 0) {
  const startMs = Date.parse(row.activated_at ?? '')
  if (Number.isNaN(startMs)) return null

  const closed = Date.parse(row.deactivated_at ?? '')
  const open = Number.isNaN(closed)
  // Clamped at the start: a stop recorded a moment before the last install —
  // or a browser clock behind the server's — would otherwise give the turn a
  // negative width.
  const endMs = open ? Math.max(startMs, endsAt) : closed

  const earned = campaignId ? sliceOf(row, campaignId) : row

  return {
    key: `${row.variant_id}-${row.activated_at}`,
    variantId: row.variant_id,
    label: row.is_original ? 'Main photo' : `Variant ${row.position}`,
    round: row.round_number,
    startMs,
    endMs,
    durationMs: Math.max(0, endMs - startMs),
    open,
    views: Number(earned?.views ?? 0),
    clicks: Number(earned?.clicks ?? 0),
    clickThrough: earned?.click_through ?? null,
  }
}

/**
 * The laps a test has served, newest first — the options of the loop picker.
 *
 * Read off the exposures rather than off `rounds_completed`: the log is what
 * the timeline draws, and a picker offering a lap with no turns in it would
 * select an empty line.
 *
 * With a campaign chosen it is the laps THAT campaign ran for. A test on its
 * tenth lap whose second campaign was switched off during the fourth offers
 * four laps under that campaign, not ten of which six are blank.
 *
 * @param {Array<object>} history Exposure rows.
 * @param {number} [campaignId] Restrict to one campaign, 0 for all.
 * @returns {Array<number>} Round numbers, highest first.
 */
export function roundsIn(history, campaignId = 0) {
  const seen = new Set(
    (history ?? [])
      .filter((row) => !campaignId || sliceOf(row, campaignId) !== null)
      .map((row) => row.round_number)
      .filter(Boolean),
  )
  return [...seen].sort((a, b) => b - a)
}

/**
 * Width one turn needs before its marker starts crowding its neighbour's: the
 * marker's own width in `TimelineMarkers.css` (52px, or 70px large) and a few
 * pixels of air.
 *
 * Sized to the marker and no more. The large size once doubled the small one,
 * 112px a turn for a 70px picture, and that bought a scroll rather than room:
 * twelve turns came out 1344px wide in a 1289px card, so the line panned on a
 * screen it fitted, the overlay scrollbar hid that it did, and the stamp naming
 * where the line ends was cut off at the card's edge.
 */
const TURN_WIDTH_PX = { small: 56, large: 74 }

/** Below this many turns the markers are drawn large; above it they are not. */
const ROOMY_TURNS = 14

/**
 * How wide the line is drawn, and how big its thumbnails may be.
 *
 * `100%` while the turns fit — the line is a proportion of the block, which is
 * what makes "All rounds" readable at a glance. Once there are more turns than
 * the block can label it becomes a fixed width and the block scrolls instead:
 * compressing a hundred turns into 1200px produces a row of hairlines and a
 * pile of overlapping thumbnails, and neither can be read or hovered.
 *
 * A short line can afford bigger pictures, and a photo is the point of one.
 *
 * @param {number} turns How many segments the line has.
 * @returns {{width: string, large: boolean}} A CSS width, and whether the
 *   markers are drawn at the larger size.
 */
export function trackSize(turns) {
  const large = turns <= ROOMY_TURNS
  const perTurn = large ? TURN_WIDTH_PX.large : TURN_WIDTH_PX.small
  return { width: `max(100%, ${turns * perTurn}px)`, large }
}

/**
 * "8 Sep" and "12:05 MSK", as two parts.
 *
 * Moscow, spelled out, because WB operates in Moscow time and the seller reads
 * these next to figures from the WB seller portal — the same rule "Rotation history"
 * follows. Two parts because the ends of the track are where the block is
 * narrowest: one such stamp on one line is the width of two thumbnails.
 *
 * @param {number|null} ms Epoch milliseconds.
 * @returns {{date: string, time: string}} The two parts, or "—" and "".
 */
export function formatStamp(ms) {
  if (ms === null || ms === undefined) return { date: '—', time: '' }
  return {
    date: formatMoscow(ms, { day: 'numeric', month: 'short' }),
    time: formatMoscow(ms, { hour: '2-digit', minute: '2-digit' }),
  }
}

/**
 * "X d Y h" or "X h Y min", or minutes alone under an hour — a lap may run for days.
 *
 * @param {number} ms A span in milliseconds.
 * @returns {string} The span in words.
 */
export function formatDuration(ms) {
  const minutes = Math.round(Math.max(0, ms ?? 0) / 60_000)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)
  if (days) return `${days} d ${hours % 24} h`
  if (hours) return `${hours} h ${minutes % 60} min`
  return `${minutes} min`
}
