/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter Tight', 'sans-serif'],
      },
      fontWeight: {
        'body': '400',
        'medium': '500',
        'semibold': '600',
        'bold': '700',
      },
      spacing: {
        'xs': '4px',
        'sm': '8px',
        'md': '16px',
        'lg': '24px',
        'xl': '32px',
      },
      borderRadius: {
        'btn': '6px',
        'card': '12px',
        'input': '8px',
      },
      boxShadow: {
        'soft': '0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px -1px rgba(0, 0, 0, 0.1)',
        // Elevation tuned for translucent (glass) cards: a wide soft ambient
        // layer plus a tight contact layer, both low-alpha.
        'card': '0 8px 32px 0 rgba(16, 16, 16, 0.1), 0 2px 8px 0 rgba(16, 16, 16, 0.05)',
      },
      fontSize: {
        'micro': '0.6875rem',
        'tiny': '0.75rem',
        'base': '0.875rem',
        'h3': '1rem',
        'h2': '1.25rem',
      },
      borderWidth: {
        // Day-section separators in the daily metrics table.
        '3': '3px',
      },
      // Semantic colors. `canvas`/`surface` are background-only and `primary`/
      // `muted` are text-only, so they live on the dedicated backgroundColor /
      // textColor scales (which merge over `colors`) — this yields the exact
      // documented classes (bg-canvas, text-primary) without the group-name/
      // utility-prefix collision that `colors.bg.canvas` would produce.
      colors: {
        status: {
          positive: '#179E60',
          negative: '#EE522B',
          warning: '#E8814F',
        },

        action: {
          DEFAULT: '#007E76',
          hover: '#17B2A8',
        },

        // Metric accents in the daily table (e.g. «Корзины» rows).
        accent: {
          indigo: '#4F46E5',
        },

        border: {
          subtle: '#E0E0E0',
        },
      },
      backgroundColor: {
        canvas: '#E8E8E8',
        // Glass surface: semi-transparent so backdrop-blur has something to
        // refract. Opaque #F1F1F1 lives on `zebra` for frozen/sticky cells.
        surface: 'rgba(241, 241, 241, 0.61)',
        // Solid surface gray: zebra stripes + sticky cells that must mask
        // content scrolling underneath them.
        zebra: '#F1F1F1',
        // Row hover in the daily table: action-default at ~12% over white
        // (solid, so the frozen first column stays opaque while scrolling).
        hover: '#E0EFEE',
      },
      textColor: {
        primary: '#101010',
        muted: '#858585',
      }
    },
  },
  plugins: [],
}
