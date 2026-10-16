---
name: design-system
description: The visual rules of this app's UI — the canvas/surface plane, the card recipe, the shared container width, the typography scale, which component library to reach for, the `ui-next` glass look and the two places glass must not go (a data grid, anything z-indexed inside a card), and the words the UI uses («кабинет», never «рабочее пространство»). Use this whenever you write or change anything a user will look at — a new page or view, a card, table, dropdown, button, form, header or empty state, any Tailwind classes, any colour or contrast question, any change to Russian UI copy or terminology, or any request phrased as "make it look right", "style this" or "match the rest of the app". Structural questions about where a component file belongs go to the frontend-architecture skill.
---

# Design system

`frontend/src/core/styles/ui-next/tokens.css` is the source of truth for every colour, shadow
and radius. `frontend/tailwind.config.js` maps the Tailwind token names (`bg-surface`,
`text-muted`, `bg-action/10`, `rounded-card`, `shadow-card`) onto those variables and holds
no values of its own; spacing and the type scale still live in the config. Colours Tailwind
consumes carry an `-rgb` channel triple in `tokens.css` so opacity modifiers work.

**There is one palette.** Tailwind's stock colours (`slate-*`, `emerald-*`, `teal-*`, …) are
replaced, not extended — they do not exist in this app, and a stock class in markup compiles to
nothing. `frontend/tests/integration/design-tokens.spec.js` fails on a stock class anywhere in
`src/` and on any literal colour in the config. This was learned the hard way: until 2026-09-26
the config still held the previous palette (teal `#007E76`, grey `#E8E8E8`/`#F1F1F1`) and only
utility classes in markup were re-pointed, so every `@apply` — the table paginator, the totals
row, the phone record cards — shipped in the old colours next to pages in the new ones.

**Never use an arbitrary value where a token exists.** `h-[123px]` or `bg-[#123123]` in a diff
means either the token was not looked for or a token is missing — work out which.

One structural gotcha: `canvas`/`surface` live on the `backgroundColor` scale and
`primary`/`muted` on `textColor`, not under `colors`. That is what makes `bg-canvas` and
`text-primary` resolve without the group-name collision `colors.bg.canvas` would produce. Do not
"tidy" them into a nested `colors` block.

## The plane

Every page sits directly on `bg-canvas`; the `<body>` owns that background and a view must not
paint its own. The app header and its dropdown use the **same** `bg-canvas` with
`border-b border-border-subtle`, so chrome and content read as one continuous plane.

`bg-surface` is for elevated blocks only — cards, tables, popovers, dropdowns. The recipe is
`bg-surface border border-border-subtle rounded-card shadow-card`, padded `p-lg`.

Header nav and page content share one container: **`.app-container`** in
`src/assets/main.css` — 80rem plus two thirds of the viewport beyond it, so side margins line up
on every page. Use the class, not the literal `mx-auto w-full max-w-[calc(...)] px-md sm:px-lg`
it replaced; the class also carries the horizontal safe area (below), which the literal recipe
cannot. Views still carry their own `py-*`.

**Glassmorphism is IN, as `ui-next`.** A glass UI was built and removed once, and the rule always
said that if it returned it got **redesigned, not reassembled from leftovers** — that is what
happened. It is now the app's look. Everything below still holds about WHERE glass may go; the two
hard constraints are not stylistic.

## `ui-next` — the design system

`src/core/styles/ui-next/` IS the design system, app-wide. Three files, in load order:
`tokens.css` (custom properties on `:root`, ground, glass base, motion), `components.css` (the
`ui-`-prefixed classes that consume them), `skin.css` (re-points the app's existing Tailwind
utilities and `.app-datatable` rules at those tokens).

**How it applies.** Every view asks for the system by name — `bg-surface`, `text-primary`,
`shadow-card` — and those names resolve to the `ui-next` variables through `tailwind.config.js`,
in markup and in `@apply` alike. `main.js` imports `assets/main.css` first and the three
`ui-next` files second, so component rules in `skin.css` win on SOURCE ORDER. **A new token is
added to `tokens.css` first** (with an `-rgb` triple if it is a colour) and then named in the
config as `rgb(var(--ui-x-rgb) / <alpha-value>)` — never as a hex.

`App.vue` wraps the whole app in `<UiPage>` (ambient ground + content layer) and renders
`AppHeaderNext`. No route flags, no per-view setup: a new page inherits the system by existing.

What it changes and why — each was measured off shipping products, not guessed:

* **Ground** `#F4F4F8` canvas with **white** cards, inverting the previous `#E8E8E8`/`#F1F1F1`.
  Apple Store measures `#F5F5F7`/`#FFFFFF`, Notion `#FFFFFF`/`#F6F5F4`, Ramp `#FFFFFF`/`#F4F2F0`.
  White cards give figures their maximum contrast, which is what this app is for.
* **Depth** layered shadow ramps (Vercel's Geist stacks three at 2/4/6 %) plus a 1px ring instead
  of a border. Never one big soft blur.
* **Action** `#715FFF`. **Measured 4.39:1 on white — below the 4.5:1 AA floor for normal text.**
  It clears AA for large text only (3:1). This was a deliberate choice, but it is now app-wide, so
  every small violet item inherits it — links, `text-tiny` labels, the SKU id in the identity
  header. `#6450E8` is the same hue at 5.45:1 and is a one-token swap in `tokens.css`.
* **Glass** blur 20–28px with `saturate(175–200%)` and a 1px inset white top lip. Opacity is not
  one value — it tracks **what sits behind the surface**:

  | Behind it | Fill |
  | --- | --- |
  | Ambient ground only | 0.55–0.62 (nav, header, tooltip, ⋮ menu) |
  | Frame + a colour orb | 0.55 (the «Цены/Остатки»/«Действия» tiles) |
  | Dense figures | 0.92–0.97 (the block label panes, the calendar) |

Two hard constraints, both established by experiment rather than by reading:

* `backdrop-filter` **establishes a containing block for fixed/absolute descendants** and a new
  stacking context. Glass on the matrix's frozen rail lets the ribbon show through it — the rail
  exists to MASK. Glass belongs on chrome that floats over scrolling content, never in a data grid.
* Overrides that target markup **inside** a component whose styles are `<style scoped>` need
  `!important` or extra specificity: a scoped rule carries a `[data-v-*]` attribute and outranks
  anything `skin.css` can write. This has bitten the toolbar glass, the zebra rows and the gap rows.

There is no revert path any more, on purpose: without the three `ui-next` imports the tokens
are undefined, not old.

Anything using z-index inside a card (frozen table columns) must be contained by that card —
`isolation: isolate` on `.app-datatable` — so it can never stack above page chrome.

Widths are a separate subject: the app has one phone breakpoint (`phone:`, max-width 430px) and a
safe-area contract that `.app-container` is part of. Both live in the **phone-layout** skill —
read it before making anything narrow.

## One word for one thing

What a seller switches between — one WB seller account with its own catalogue, its own P&L
and its own tokens — is a **кабинет**. Full form «Личный кабинет», short form «Кабинет»,
plural «Кабинеты». Never «рабочее пространство»: it is an English calque, it is not what
the marketplace calls a seller's account, and it was used in eleven places while «кабинет»
was used in none.

The code still says `workspace` everywhere — model, table, store, header, route — and that
stays. The identifier is not the noun a user reads, renaming it would be a migration across
four modules, and English identifiers behind a Russian UI is how this whole codebase works.
**The rule is about the words on the screen.**

Both halves are machine-enforced, because a naming rule nobody can fail is one that drifts
back: `frontend/tests/integration/naming.spec.js` scans every `.vue`/`.js` a user can read,
and `backend/tests/unit/core/test_messages_are_russian.py` scans the exception messages the
API hands to a client. Add a new banned word to both.

## Few words, and those carry the meaning

The owner's rule (2026-10-17): **no explanatory text on the page itself, or almost none.**
A state the user has to understand — data late, WB refusing, a number estimated, a figure
missing — is shown by an icon, a colour, a badge or a dedicated block, and the explanation
lives behind it in a tooltip or a popover. A sentence added to the page to explain
something is the wrong answer even when the sentence is right.

The words that do appear are laconic: the most meaning in the fewest words. «WB ещё не
отдал вчера», not «К сожалению, Wildberries пока не предоставил данные за вчерашний день».
No apologies, no "please", no restating what the icon already says. A user should get the
problem at a glance and the detail in one hover.

## Type

| Role | Classes |
| --- | --- |
| KPIs and main titles | `text-h2 font-bold text-primary` |
| Labels and descriptions | `text-tiny font-medium text-muted` |
| Body and data | `text-base font-body text-primary` |

## Components

Do not build a complex component from scratch. Basic elements — buttons, inputs, cards, dialogs,
selects — follow shadcn-vue's styling written in plain Tailwind. Data tables are **PrimeVue** in
unstyled/Tailwind mode; the analytics tables need its sorting, sticky headers and frozen columns,
and hand-rolling that has already been tried and lost.

Placement: `core/components/` for reusable atoms, `modules/<name>/components/` for
domain-specific molecules, `views/` for page composition. Check `core/components/` before writing
a new atom, and remember the 250-line ceiling per `.vue` file — it is a test, not a guideline.

### The shared building blocks — use them, never redraw them

Every element below was drawn three to six different ways before October 2026; each now has
one home. A page that needs one of these uses it; a page that needs something they cannot do
extends the shared one rather than growing a local copy.

| Need | Use |
| --- | --- |
| Any button | `.ui-btn` + `--primary` / `--ghost` / `--danger` (+ `.is-armed`) / `--good` / `--sm`; `.ui-icon-btn` for an icon. In `assets/main.css`'s components layer, so utilities still win |
| An irreversible action | `core/utils/confirmClick.js` — two presses, «Точно …?», withdraws after 4 s |
| A text field / a select | `.ui-input` / `.ui-select` (+ `--sm`); width is the caller's |
| A search box | `core/components/SearchField.vue` — it draws the one ✕; the browser's own is hidden for every `.ui-input[type=search]` |
| A filter over articles («Предметы», «Бренды», «Артикулы») | `core/components/FilterMenu.vue` — a glass, searchable checklist, several choices; never a native `<select>` |
| «Группы» | `GroupsFilter` from `@/modules/heatmap` — beside «Предметы» and «Бренды» on every page that has them; the list is one store (`useGroupsStore`), so a group made on one page is on all of them, and `articlesOfGroups` turns the choice into nm_ids |
| How a table or chart is cut («Артикулы · Предметы · Бренды · Группы») | `core/components/GroupingChips.vue`, at the top right of the block it cuts and outside it — beside the block title (summary, advertising), at the right end of the filter row above it (heatmap, balance), or before «Строк на странице» (P&L). Rows by subject/brand/group are sums of their articles (`splitBy` from `@/modules/heatmap`); the «Итого» is summed over the articles, because by group one article sits in several rows |
| A chosen option among a few | `.ui-chip` / `.is-on` (filled with the action colour, never a raised white card) |
| An on/off mode | `core/components/UiSwitch.vue` |
| A status | `.ui-badge` + `.is-ok` / `.is-warn` / `.is-bad` / `.is-soft` / `.is-on` / `.is-quiet` |
| The top of a page | `core/components/PageHeader.vue`; the page root is `div.app-container py-lg` |
| A headline figure | `core/components/KpiTile.vue` |
| An explanation on a label | `core/components/InfoHint.vue` — never a `title` attribute. One short plain sentence, no formulas |
| Any floating tip over a table | Teleported, and kept inside the table's visible area: `visibleArea(anchor)` on open + `v-fit-inside` on the bubble (`core/utils/tipFit.js`). A tip that hangs past the card's edge is a bug |
| A list behind one cell (an article's penalty reasons) | Never extra lines in the cell — a table row is one line high. A count pill («5 причин») beside the figure, and ONE card per table, opened on click, owned by the table rather than the cell (PrimeVue re-renders a cell on a row click and would close it): `finreports/components/PnlPenaltyReasons.vue` |
| Child rows under a row (an article's sizes) | Rows of the SAME table, in the same columns, under their parent: tinted, smaller, a size pill in the frozen column, blank where the child has no such figure, no «Итого» of their own (the parent row is it). Never a nested table — see `finreports/pnlSkuTree.js` |
| A modal question | `core/components/UiDialog.vue` («Отмена» before the main action) |
| Loading, empty, failed | `core/components/DataState.vue`; a reload keeps the figures in `BusyRegion.vue` |
| More records | `core/components/ShowMoreButton.vue` — «Показать ещё (N)» |
| A table | PrimeVue or a hand-drawn `<table>` inside `.app-datatable`; `SortIcon.vue` for a hand-drawn sort. A figure column reads from the right — head, cells and «Итого»: `class="col-num"` on a PrimeVue `<Column>`, `text-right tabular-nums` on a hand-drawn one. Identifiers (Артикул WB) and text stay left |
| A number | `core/utils/format.js` — «—» is no figure, «0» is zero; never `toLocaleString` in a page |

Left different on purpose — do not "fix" these:

* The monitoring matrix, the balance and the stock comparison keep their dense small head and
  leave empty cells blank: every pixel saved is one more warehouse column, and a «—» in every
  empty cell is noise.
* The heatmap prints percentages without «%» — the unit is in the metric's name.
* Logistics keeps kopecks: those sums go into a claim.
* The change-password form has its own «показать пароль»: one press shows all three fields.
* The logistics page picks a week, not a period — the owner's call.
* `labs/` are sandboxes with their own look.

### Dates and periods

A period is picked with `core/components/PeriodSelector.vue`, one day with `DayPicker.vue` —
both drawn in `CalendarShell.vue`, so they share the trigger, the popover and its phone layout
(one month below 640px, 44px days). A page never draws a date control or quick presets of its
own: the presets (7/30/90 and «Вся история» or «180 дней») live only in the calendar's footer.
Two rows of presets for one window is how the summary once lit two of them at once.

A page states its bounds and the calendar enforces them as greyed days: `history-from` (first
day with data — also what turns «180 дней» into «Вся история»), `max` (last pickable day),
`max-days` (longest window, both ends counted — mirror the backend's cap, whose
`MAX_WINDOW_DAYS` counts days *between* the ends, hence the `+ 1`), and `preset-end`. Every
preset window, the one lit preset and a page's default window come from `presetWindow` /
`activePreset` in `core/utils/calendarModel.js`; a default built any other way opens the page
with nothing lit. The chosen period is kept by `core/utils/periodMemory.js` — an hour, per page
and per кабинет — never by a page's own storage.

Nothing here is machine-checked (there is no visual-regression tier), so a UI change is verified
by looking at it: run the app and screenshot the surface you changed.
