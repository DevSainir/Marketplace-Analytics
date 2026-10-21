---
name: phone-layout
description: How this app adapts to a phone — the single `phone:` breakpoint (≤430px, sized for an iPhone 17 Pro's 402pt), the safe-area contract that `viewport-fit=cover` obliges us to honour, and the recipes for the things that do not fit a 390–410px screen (wide tables become one card per record, toolbars wrap, side-by-side panels stack). Use this for any request about mobile, phones, iPhone, "adaptive", "responsive", a viewport width in the 375–430 range, or a page that "looks broken on my phone" — and whenever you add a view, table, toolbar or dropdown that has to survive one. Colours, spacing and the card recipe stay in the design-system skill; this one is only about width.
---

# Phone layout

The app is a desktop analytics tool that must stay usable on a phone. It is **not** a
mobile-first product with a desktop bonus, and the rules below exist to keep phone work from
leaking into the desktop layout that people actually work in all day.

## One breakpoint, and it is a max-width

```js
// frontend/tailwind.config.js
screens: { phone: { max: '430px' } }
```

Everything else in the app is mobile-first — `sm:` (640) / `md:` / `lg:` are min-width — so an
unprefixed class already **is** the phone style. `phone:` sits under all of them as the single
max-width query.

Three consequences, in order of how often they matter:

1. **A `phone:` class can only narrow the design.** Desktop is provably untouched by anything you
   add there, so a phone fix never needs a desktop regression check. This is the whole reason the
   breakpoint is max-width rather than another min-width step.
2. **Reach for the unprefixed class first.** If the change should also apply at 500px or 900px it
   belongs in the base classes with an `sm:` override, not in `phone:`. `phone:` is for what is
   true *only* on a phone.
3. **Do not add a second phone breakpoint.** One supported width band, one query. 430px is the top
   of the modern iPhone band — 390pt on 12–14, **402pt on the 15/16/17 Pro**, 428–430pt on the Max
   models — so the 390–410px target sits inside it with room either side. A `phone-sm` for 375pt
   is not on the table; make the 390 case work and the 375 case follows.

## Safe areas are already paid for — do not re-pay them

`index.html` sets `viewport-fit=cover`, so the canvas runs edge to edge under the Dynamic Island
and the home indicator and the layout owes the insets itself. That debt is settled in exactly
three places, all in `frontend/src/assets/main.css`:

| Where | What it does |
| --- | --- |
| `.app-container` | side gutter is `max(px-md / sm:px-lg, env(safe-area-inset-left/right))` |
| `.pt-safe` on the sticky `<header>` | header canvas fills the Dynamic Island strip |
| `.pb-safe` on `<main>` in `App.vue` | every route clears the home indicator |

So: **a view never writes `env(safe-area-inset-*)`.** It uses `.app-container` and inherits the
rest. `.pt-safe` / `.pb-safe` *set* padding rather than add to it, which is why they only ever go
on an edge that has no padding of its own — putting `.pb-safe` on a view with `py-lg` would eat
its bottom padding. All three resolve to `0px` where there is no inset, so none of this is
visible on a desktop.

The horizontal inset is ~59px in landscape. That is what the `max()` is for, and it is why a
full-bleed element that escapes `.app-container` (a table that spans the viewport, a fixed bar)
has to think about it again.

## Converting a page

`.app-container` is the shared width + gutter (see the design-system skill). Swap the literal
`mx-auto w-full max-w-[calc(26.667rem_+_66.667vw)] px-md sm:px-lg` for it as you go — the views
still carry their own `py-*`.

Then, roughly in the order the problems bite:

**Anything wider than the screen becomes a stack of cards, one record per card.** This is the
rule that does the most work. A table the user has to scroll sideways to read is not adapted, it
is merely not broken: they lose the row they were on the moment they scroll. Render the same data
twice — the table and a card list — driven by the same computed rows, so there is one source of
truth and no `v-if` on window width.

The recipe, as `finreports/components/styles/RecordCards.css` implements it, is a **row, not a
card**: two lines separated by a hairline — identity and the lead figure on the first, the
qualifiers on the second — with everything else behind the row itself, which is the disclosure
control. It was a padded card with a border, a shadow and its own «Подробнее» button first, and
that ran to one screen every two records; nobody scrolls a forty-SKU report at that density. Aim
for ~50px per record and roughly a screenful per page of results.

**An EDITABLE grid folds nothing away.** Its row exists to be typed into, so the input stays on
screen and the row is not a disclosure at all (`.record-line` instead of `.record-summary`) — what
the desktop spends columns on becomes the second line as metadata. Two consequences worth knowing:
a row whose value you just saved may sort out of the visible page (uncosted-first ordering), and
edits made on rows since scrolled past stay in the draft and still save — the pending count on the
save button is what says so.

Deciding which figures lead is the actual design work — «Чистая прибыль» leads a P&L row because
that is what a seller opens the page for, and the fine's category stays with its figure because
that is what says whether it is disputable. Three things such a list needs that a table gets from
its headers:

* **a sort control**, since there are no headers to click (a `<select>` plus a direction toggle);
* **incremental growth** — a «Показать ещё» rather than a paginator, so finding the next
  loss-maker is a scroll and not a page hunt. **10 rows a page**: the desktop table's 50 is sized
  for a screen five times as tall;
* **the totals first.** A corner total in a grid becomes a card at the TOP of the list, or the
  reader reaches it only after every record. Not a bar stuck to the bottom of the screen: the
  P&L tried that and it cost a permanent strip of a 874pt screen to say what the top of the
  list already says; it moved to the top on 2026-10-09, like advertising and the heatmap.

Colour the values through the sheet's own **modifier** classes (`.record-value--negative`,
`--warning`, `--muted`), never a bare `text-status-*` utility beside `.record-value`: the scoped
class already sets `text-primary` and outranks the utility, so the colour silently does not apply.

The offender that pushes a page sideways is rarely the table — it is contained by its own
`overflow-x`. It is a **toolbar row that cannot wrap**: a `<select>` whose widest option is 300px
next to a button, in a `flex` with no `flex-wrap`. `flex-wrap` plus `min-w-0` on the select is the
whole fix, and it is worth checking every filter row for it.

A **matrix** — rows × N repeating column groups, like the daily metrics grid (18 metrics × 30 days
× 8 traffic columns) — has no "record" to make a card of, and it is tempting to conclude that
sideways scrolling is simply its reading model and keep the table. That was tried here and it is
wrong twice over. Sized to fit, the leaf columns land around 10px and the numbers print on top of
one another; sized to their content, one day runs several screens wide and the reader swipes
through mostly-empty columns to reach the totals, with the date centred across a span so wide it
is off-screen for most of its own day.

Once the axis is paged, everything else that is *per-day* joins the same page — the note and the
«Действия» answers are sections of the day list, not separate screens. Their editing rules travel
with them and are about the data, not the layout (a budget locked until its campaign is chosen, a
type disabled in the other slot, clearing a choice taking its amount with it), so port them
verbatim rather than re-deriving them; a form that silently drops an edit is worse than a table
that scrolls.

What works is **paging the repeating axis**: pick one day, render its rows as a vertical list, and
put a `‹ 19.07.2026 (вс) ›` pager above it. The sub-columns fold into a per-row disclosure and are
shown only when something other than the headline column carries a value. See
`modules/monitoring/dayListRows.js` + `MetricsDayList.vue` — the list projects the SAME `row.cells`
the table renders, so there is one matrix with two projections and never two sources of truth.

**Where to put the table/list switch.** Not at `phone:`. Swapping one component for another is a
capability threshold, not a phone tweak: the metrics table needs ~640px before its columns stop
overlapping, so the pair is gated `sm:hidden` / `hidden sm:block`. `phone:` stays for tuning
things that render at every width. Gating a swap at 430px leaves 431–639px rendering the broken
desktop layout, which is exactly the bug report that produced this paragraph.

**Toolbars and filter rows wrap rather than shrink.** `flex-wrap` plus `phone:w-full` on the
controls, so each lands on its own full-width line instead of being squeezed to a stub. A control
whose label disappears below ~120px should show an icon + `aria-label`, not a truncated word.

**Side-by-side panels stack.** Two-up comparisons (the stock compare panel) become one column
with a clear heading per side; do not try to keep two tables at 190px each.

**Tap targets are 44px.** `phone:min-h-11` on buttons and links, `phone:py-md` on menu and list
rows. The desktop `py-sm` row is 37px and is a miss on a phone.

**Vertical air is desktop's, not the phone's.** A `py-16` hero or `mt-20` section gap costs a
fifth of the screen. Cut it with `phone:py-lg` / `phone:mt-xl`. Display type usually drops one
step (`text-4xl` → `phone:text-3xl`); body type does not — `text-base` is already 14px here, so
shrinking it further makes it unreadable, tighten `leading` instead.

## Verifying

There is no visual-regression tier, so this is looked at, not asserted. Run the dev server
(`preview_start` with the `frontend` config) and check **402×874** — the 17 Pro — plus **390×844**
as the narrow end of the band.

Two gotchas that have already cost time:

* **`tailwind.config.js` changes need a dev-server restart.** Vite's HMR reloads the CSS but not
  the Tailwind config, so a new screen or token silently does not exist and you will conclude your
  classes are wrong. `preview_stop` then `preview_start`.
* **Assert the absence of overflow, do not eyeball it.** A screenshot hides a 4px overrun:

  ```js
  // javascript_tool
  ;[...document.querySelectorAll('*')]
    .filter((e) => e.getBoundingClientRect().right > innerWidth + 1)
    .map((e) => e.tagName + '.' + e.className)
  ```

  and check `document.documentElement.scrollWidth === innerWidth`.

Before trusting what you see locally, check whether the data itself is synthetic. `WB_FAKE_HARVEST`
stock used to invent its `chrt_id`s, so every size in «Остатки по складам» rendered as a bare
`chrt 5352…` — a local-only artefact that looks exactly like a layout bug. It now reuses the SKU's
catalogued sizes, but the lesson generalises: when a phone screenshot shows something odd, confirm
the data is real before redesigning around it.

Every page except `/` and `/login` is behind the auth guard, so the browser preview shows you an
empty shell. Drive those from a throwaway Playwright script that imports `CREDENTIALS` and the
login flow from `tests/end-to-end/fixtures/app.js` — the seeded account, already in the repo —
with `chromium.launch({ channel: 'chrome' })` so it uses the system browser instead of
downloading one. A `deviceScaleFactor: 2`, `isMobile: true` context is what makes the capture
match a real phone. Delete the script when you are done; it is scaffolding, not a test.

Safe-area insets are always `0px` in a desktop browser — no engine lets you fake them — so the
`env()` behaviour is verified by reading the computed rule, not by seeing it. The `max()` fallback
resolving to the design gutter is the part you *can* check.

## Converted so far

| Surface | State |
| --- | --- |
| App chrome (`AppHeader`, `WorkspaceMenu`, `App.vue`) | done — the nav scrolls sideways at phone width, and the active link is scrolled into view on every route change (it sat off-screen past «Сводка») |
| `/` — `HomeView` | done |
| `/monitoring` | done — metrics matrix, prices/stock, the per-day note and «Действия», search, toolbar, stock compare |
| `/profile` | done — label/value pairs stack, the admin panel's workspace rows split into an identity line and an actions line |
| `/login` | done — and moved onto the design-system tokens on the way, which it had never been on |
| `/finreports` (P&L) | done — the 18-column SKU table and the SKU × warehouse balance grid both become card lists below `sm`; an opened SKU card carries its sizes as a two-line list per size (`PnlSkuSizeList`), since the 16-column size table cannot fit. Checked 390 / 402 / 768 px, 2026-09-26: no horizontal overflow |
| `/finreports/cost-prices` | done — the editable grid becomes rows with the input still on screen |
| `/heatmap` | done — the articles × days grid pages its column axis below `sm` (`HeatmapDayList`): one day, week or month per screen, «Итого» first, each article one line with its tinted value (and, with «Норма: ручной ввод», a 16px norm field labelled just «Норма» or «Норма в день»); filters and selects go full width |
| `/ab-tests/:id` | done — the photos × metrics grid pages its photo axis (`VariantMetricsPager`), one photo and its seven figures per screen; the turn log keeps its table and drops its two widest columns |

Keep this table honest; it is how the next session knows where to pick up.
