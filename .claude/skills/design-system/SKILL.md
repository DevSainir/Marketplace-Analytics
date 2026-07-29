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

Header nav and page content share one container width:
`mx-auto w-full max-w-[calc(26.667rem_+_66.667vw)] px-md sm:px-lg` — 80rem plus two thirds of
the viewport beyond it, so side margins line up on every page.

**No glassmorphism.** `backdrop-blur`, `backdrop-saturate` and translucent surfaces
(`bg-surface/NN`, `bg-white/NN`, rgba surface tokens) are out. A glass UI was built and removed;
if it ever returns it gets redesigned, not reassembled from leftovers. This is also why `zebra`
exists as a separate token for the same grey `surface` uses.

Anything using z-index inside a card (frozen table columns) must be contained by that card —
`isolation: isolate` on `.app-datatable` — so it can never stack above page chrome.

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
