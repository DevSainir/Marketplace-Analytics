---
name: design-system
description: The visual rules of this app's UI — the canvas/surface plane, the card recipe, the shared container width, the typography scale, which component library to reach for, and the design decisions that already failed once (glassmorphism, translucent surfaces, z-index escaping a card). Use this whenever you write or change anything a user will look at — a new page or view, a card, table, dropdown, button, form, header or empty state, any Tailwind classes, or any request phrased as "make it look right", "style this" or "match the rest of the app". Structural questions about where a component file belongs go to the frontend-architecture skill.
---

# Design system

`frontend/tailwind.config.js` is the source of truth for every token — colours, spacing, radii,
shadows, type scale — and it carries comments explaining the odd ones. Read it rather than a
copy; a copy drifts. This skill records the decisions the config cannot state.

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

**How it applies without touching markup.** Every view already asks for the system by name —
`bg-surface`, `text-primary`, `shadow-card`. `main.js` imports `assets/main.css` first and the
three `ui-next` files second, so identical selectors in `skin.css` win on SOURCE ORDER. That also
makes it reversible: drop the three imports and the app is exactly as it was.
`tailwind.config.js` still holds the previous palette and is still what `@apply` resolves against —
**a new colour/shadow/radius token added there must be added to `skin.css` too**, or that one
utility keeps rendering the old value.

`App.vue` wraps the whole app in `<UiPage>` (ambient ground + content layer) and renders
`AppHeaderNext`. No route flags, no per-view setup: a new page inherits the system by existing.

What it changes and why — each was measured off shipping products, not guessed:

* **Ground** `#F4F4F8` canvas with **white** cards, inverting the current `#E8E8E8`/`#F1F1F1`.
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

**Reverting** is dropping the three `ui-next` imports from `main.js`. Everything else — the tokens
in `tailwind.config.js`, the `.app-datatable` skin in `main.css`, every view's classes — is
untouched and still describes the previous look.

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

Nothing here is machine-checked (there is no visual-regression tier), so a UI change is verified
by looking at it: run the app and screenshot the surface you changed.
