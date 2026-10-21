/**
 * The palette offered by the pinned-row paint tool.
 *
 * **Three colours, not thirteen.** The row previously offered the Open Color
 * shade-2 ramp — thirteen macaron pastels spanning the whole hue circle. Two
 * problems with that, and the second is the one that matters:
 *
 * * it belonged to no design system, so a painted chip was the only thing on
 *   the page whose colour came from somewhere else, and the row read as a
 *   child's highlighter set next to `ui-next`'s single violet accent;
 * * thirteen choices is not thirteen times as useful as three. The colour is a
 *   grouping mark on a row of chips a manager scans sideways — "these three I
 *   look at together". Past a handful, telling `#d8f5a2` from `#b2f2bb` at chip
 *   size costs more attention than the grouping saves.
 *
 * These three are the system's own hues (`tokens.css`: action `#715FFF`,
 * positive `#067A52`, warning `#C2700B`) taken to a tint light enough that
 * `--ui-ink` stays comfortably readable on them, and far enough apart in hue to
 * separate at a glance. They carry no status meaning — a pin is not «good» or
 * «bad» — they are simply this system's three most distinguishable marks.
 *
 * Plain hex, not Tailwind tokens, because the colour is DATA: it round-trips
 * through the API (`PinColorUpdateRequest`, validated as `#rrggbb`) and is
 * applied as an inline custom property.
 *
 * The API still accepts any `#rrggbb`, so a pin painted from the old palette
 * keeps rendering its stored pastel until someone repaints it. That is
 * deliberate — silently rewriting a customer's saved colours is worse than a
 * few legacy chips — but it does mean the old tints do not disappear from
 * existing workspaces on deploy.
 */
export const PIN_COLORS = [
  { value: '#E3DEFF', label: 'Сиреневый' },
  { value: '#D3E8DE', label: 'Зелёный' },
  { value: '#F2E4CC', label: 'Песочный' },
]
