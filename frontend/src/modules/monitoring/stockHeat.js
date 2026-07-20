/**
 * The stock heatmap scale: remaining units → tint intensity.
 *
 * A single monochrome ramp, applied to every warehouse × size cell of the
 * stock tables. Darker = more units sitting there.
 *
 * ## Why the scale is GLOBAL, not per-table
 *
 * The anchors below are fixed constants, so a given tint means the same
 * number of units in every table, for every SKU, on every day. That is the
 * whole point: the two day tables render side by side for visual dynamics,
 * so the eye must be able to compare them directly. Normalising per table
 * would break that — and worse, it would be a lie in the common case: per-day
 * per-SKU maxima in the data run from 1 to 202, so a table whose fullest cell
 * holds a single unit would paint that unit at full intensity and read as a
 * stuffed warehouse.
 *
 * ## Why the anchors are spaced the way they are
 *
 * Remaining stock is heavily right-skewed. Measured over the whole
 * `monitoring.stock_snapshot` table (11,184 non-zero cells across 30 SKUs):
 *
 *     percentile   10  20  30  40  50  60  70  80  90  95  99   max
 *     units         1   1   1   1   2   3   5  12  27  44  74   202
 *
 * 43% of non-zero cells hold exactly 1 unit and 71% hold ≤5. Interpolating
 * linearly from 0 to the maximum would therefore leave three quarters of the
 * table an indistinguishable pale wash while a single outlier pile carried
 * the entire ramp — a heatmap that hides exactly the mid-range differences
 * it exists to show.
 *
 * So the ramp is piecewise-linear (plain linear interpolation BETWEEN the
 * stops) over anchors placed at data quantiles instead of at even unit
 * intervals, which spends the colour range where the cells actually are.
 * Above the top stop (~p99) the ramp clamps, so the 202-unit outlier cannot
 * re-flatten everything below it.
 *
 * The stops are hand-rounded to stock levels a merchandiser reads naturally
 * (1 / 5 / 12 / 27 / 44 / 80) — they track the 70th–99th percentiles.
 *
 * ## Empty cells are ON the ramp
 *
 * Zero sits at the bottom stop rather than off the scale, so the grid reads
 * as one continuous field instead of a tint pocked with holes. It has to be
 * the faintest possible step and still land: empty cells OUTNUMBER stocked
 * ones about 4:1 (a typical table is ~80% empty), so anything heavier than a
 * whisper would wash the whole table blue and drown the signal it exists to
 * carry. Empty cells stay blank of text, so the tint is all that separates
 * "nothing here" from "one unit" — hence the deliberate gap between the first
 * two stops, wider than a purely quantile-driven cut would give.
 *
 * ## Re-checking the anchors
 *
 * They are calibration, not law: if the catalogue's stocking profile shifts,
 * re-run the distribution and re-cut the stops.
 *
 *     SELECT unnest(ARRAY[50,70,80,90,95,99]) AS pctile,
 *            unnest(percentile_cont(ARRAY[0.5,0.7,0.8,0.9,0.95,0.99])
 *                   WITHIN GROUP (ORDER BY quantity)) AS qty
 *       FROM monitoring.stock_snapshot WHERE quantity > 0;
 */

/**
 * The ramp's hue, as bare `r, g, b` channels for interpolation into `rgba()`.
 *
 * ColorBrewer "Blues" step 6 — a sequential palette built for exactly this
 * job. Its ~54% saturation is the point: the obvious pick (sky-500, #0EA5E9)
 * reads as a highlighter at 89% saturation, far too electric to sit in a
 * muted grey/teal UI for hours. This is the same family of blue with the
 * chroma taken out, so it stays calm without going dishwater-grey.
 *
 * It also stays clear of the palette's load-bearing hues — the action teal
 * (#007E76, which marks shipped warehouses right there in the header) and the
 * «Корзины» indigo — so a heat tint can never be misread as a state.
 */
const HEAT_RGB = '66, 146, 198'

/**
 * Intensity anchors: `units` → `t` on the [0, 1] ramp. Ascending by `units`;
 * `t` is interpolated linearly between neighbours (see `heatIntensity`).
 */
const HEAT_STOPS = [
  { units: 0, t: 0.05 },
  { units: 1, t: 0.14 },
  { units: 5, t: 0.3 },
  { units: 12, t: 0.47 },
  { units: 27, t: 0.65 },
  { units: 44, t: 0.82 },
  { units: 80, t: 1 },
]

/**
 * Alpha at full intensity. Short of 1 so the densest cell still reads as a
 * tinted cell rather than a solid block: it keeps the zebra stripe and the
 * row-hover tint underneath faintly alive, and leaves the table looking like
 * a table rather than a bar chart.
 *
 * It is also the readability budget. The darkest cell still carries an 11px
 * number in `text-primary`, and this ceiling is what holds that at ~7.3:1 —
 * past WCAG AAA, so no cell ever has to flip to white text. Raising it (or
 * deepening HEAT_RGB) spends that margin; re-measure if either changes.
 */
const MAX_ALPHA = 0.78

/** The floor: an empty cell's intensity, and so the ramp's true left edge. */
const MIN_T = HEAT_STOPS[0].t

/**
 * The legend's ticks: the anchors themselves, top one open-ended.
 *
 * `pos` is the tick's place along the BAR, not its raw intensity — the bar
 * spans [MIN_T, 1] (no cell can be fainter than an empty one), so the stops
 * are renormalised onto that span rather than onto [0, 1].
 */
export const HEAT_LEGEND_TICKS = HEAT_STOPS.map((stop, index) => ({
  label: index === HEAT_STOPS.length - 1 ? `${stop.units}+` : `${stop.units}`,
  t: stop.t,
  pos: (stop.t - MIN_T) / (1 - MIN_T),
}))

/**
 * Position on the [0, 1] ramp for a remaining-units count.
 *
 * A missing count (`null`/`undefined` — the comparison tables impose a shared
 * row set, so a size one day never stocked has no entry at all) means zero
 * units, which is a real reading and gets the floor tint like any other
 * empty cell. Above the last anchor the ramp clamps.
 */
export function heatIntensity(units) {
  const value = units > 0 ? units : 0

  for (let i = 1; i < HEAT_STOPS.length; i += 1) {
    const prev = HEAT_STOPS[i - 1]
    const stop = HEAT_STOPS[i]
    if (value <= stop.units) {
      const progress = (value - prev.units) / (stop.units - prev.units)
      return prev.t + progress * (stop.t - prev.t)
    }
  }
  return 1
}

/**
 * The ramp colour at a raw intensity. Exported for the legend, which walks
 * the ramp by `t` directly rather than by units.
 */
export function heatFillAt(t) {
  return `rgba(${HEAT_RGB}, ${(t * MAX_ALPHA).toFixed(3)})`
}

/** The cell tint for a remaining-units count. Every cell gets one. */
export function heatFill(units) {
  return heatFillAt(heatIntensity(units))
}
