/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js}'],
  theme: {
    // Tailwind's stock palette is REPLACED, not extended: `slate-100`,
    // `emerald-600`, `teal-*` and the rest do not exist in this app. Every
    // colour is a design-system token below, resolved to `ui-next`, so there is
    // no second palette to reach for by accident. A stock class in markup is
    // dropped silently by the compiler, which is why
    // tests/integration/design-tokens.spec.js scans for them.
    colors: {
      transparent: 'transparent',
      current: 'currentColor',
      inherit: 'inherit',
      white: '#ffffff',
      black: '#000000',
    },
    extend: {
      // The app's ONE phone breakpoint. Everything else here is mobile-first
      // (`sm:` and up), so `phone:` is deliberately a MAX-width query: it can
      // only ever narrow the default layout and desktop is provably untouched.
      // 430px is the top of the modern iPhone band — 12/13/14 are 390pt,
      // 15/16/17 Pro are 402pt, the Plus/Max models 428–430pt — so the
      // 390–410px target sits comfortably inside it with room either side.
      screens: {
        phone: { max: '430px' },
      },
      fontFamily: {
        sans: ['Inter Tight', 'sans-serif'],
      },
      fontWeight: {
        body: '400',
        medium: '500',
        semibold: '600',
        bold: '700',
      },
      spacing: {
        xs: '4px',
        sm: '8px',
        md: '16px',
        lg: '24px',
        xl: '32px',
      },
      // Radii, shadows and colours are NOT values here — each resolves to the
      // `ui-next` custom property that defines it (src/core/styles/ui-next/
      // tokens.css). One definition, so a utility in markup and an `@apply` in
      // a stylesheet can never render two different looks. Until 2026-09-26
      // this file held the previous palette, and every `@apply` compiled to it.
      borderRadius: {
        btn: 'var(--ui-r-sm)',
        card: 'var(--ui-r-lg)',
        input: 'var(--ui-r-sm)',
      },
      boxShadow: {
        soft: 'var(--ui-sh-xs)',
        card: 'var(--ui-sh-md)',
      },
      fontSize: {
        micro: '0.6875rem',
        tiny: '0.75rem',
        base: '0.875rem',
        h3: '1rem',
        h2: '1.25rem',
      },
      borderWidth: {
        // Day-section separators in the daily metrics table.
        3: '3px',
      },
      // Semantic colors. `canvas`/`surface` are background-only and `primary`/
      // `muted` are text-only, so they live on the dedicated backgroundColor /
      // textColor scales (which merge over `colors`) — this yields the exact
      // documented classes (bg-canvas, text-primary) without the group-name/
      // utility-prefix collision that `colors.bg.canvas` would produce.
      //
      // `<alpha-value>` is what keeps `bg-action/10` and the like working
      // against a variable: Tailwind substitutes the opacity into the channel
      // triple rather than trying to parse a colour it cannot see.
      colors: {
        status: {
          positive: 'rgb(var(--ui-pos-rgb) / <alpha-value>)',
          negative: 'rgb(var(--ui-neg-rgb) / <alpha-value>)',
          warning: 'rgb(var(--ui-warn-rgb) / <alpha-value>)',
        },

        action: {
          DEFAULT: 'rgb(var(--ui-action-rgb) / <alpha-value>)',
          hover: 'rgb(var(--ui-action-hover-rgb) / <alpha-value>)',
        },

        // Metric accents in the daily table (e.g. «Корзины» rows).
        accent: {
          indigo: '#4F46E5',
        },

        border: {
          subtle: 'rgb(var(--ui-hairline-rgb) / <alpha-value>)',
          // The outline of a ghost button: the hairline vanishes against the
          // canvas, so this is the muted ink at a low alpha (`/25`).
          strong: 'rgb(var(--ui-muted-rgb) / <alpha-value>)',
        },
      },
      backgroundColor: {
        canvas: 'rgb(var(--ui-canvas-rgb) / <alpha-value>)',
        surface: 'rgb(var(--ui-surface-rgb) / <alpha-value>)',
        zebra: 'rgb(var(--ui-zebra-rgb) / <alpha-value>)',
        // A drill-down panel inside a card; see tokens.css.
        inset: 'rgb(var(--ui-inset-rgb) / <alpha-value>)',
        // The one hover fill for anything sitting on canvas/surface.
        hover: 'rgb(var(--ui-action-soft-rgb) / <alpha-value>)',
      },
      textColor: {
        primary: 'rgb(var(--ui-ink-rgb) / <alpha-value>)',
        muted: 'rgb(var(--ui-muted-rgb) / <alpha-value>)',
      },
    },
  },
  plugins: [],
}
