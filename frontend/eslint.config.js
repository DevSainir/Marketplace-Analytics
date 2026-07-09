/**
 * ESLint flat config with strict architectural boundary enforcement.
 *
 * Fatal (error-level) architectural rules:
 *   1. Horizontal Import Violation — a file in `src/modules/A/` may NEVER
 *      import internals of `src/modules/B/`; only `@/modules/B` (its
 *      `index.js` Public API) is allowed.
 *   2. Downward Import Violation — `src/core/` must stay module-agnostic.
 *      The single exception is the main router, which aggregates route
 *      arrays from module Public APIs.
 *   3. Relative Path Abuse — parent-relative imports (`../`) are forbidden
 *      everywhere; the absolute `@/` alias must be used instead.
 *
 * Modules are auto-discovered from `src/modules/`, so a new module gets its
 * own-internals exception without touching this file.
 */
import { readdirSync } from 'node:fs'

import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

const MODULES = readdirSync(new URL('./src/modules', import.meta.url), {
  withFileTypes: true,
})
  .filter((entry) => entry.isDirectory())
  .map((entry) => entry.name)

const RELATIVE_PARENT_PATTERN = {
  group: ['../*', '../**'],
  message: 'Parent-relative imports are forbidden. Use the absolute "@/" alias.',
}

const PUBLIC_API_ONLY_PATTERN = {
  group: ['@/modules/*/*', '@/modules/*/**', '!@/modules/*/index.js'],
  message:
    'Deep imports into a module are forbidden. Import from the module Public API: "@/modules/<name>".',
}

export default [
  { ignores: ['dist/**', 'node_modules/**'] },

  js.configs.recommended,
  ...pluginVue.configs['flat/essential'],

  {
    languageOptions: {
      globals: { ...globals.browser },
    },
    rules: {
      'vue/multi-word-component-names': ['error', { ignores: ['App'] }],
    },
  },

  // Vitest globals for colocated spec files.
  {
    files: ['src/**/*.spec.js'],
    languageOptions: {
      globals: {
        describe: 'readonly',
        it: 'readonly',
        expect: 'readonly',
        vi: 'readonly',
        beforeEach: 'readonly',
        afterEach: 'readonly',
      },
    },
  },

  // Global boundary rules: no parent-relative paths, no deep module imports.
  {
    files: ['src/**/*.{js,vue}'],
    rules: {
      'no-restricted-imports': [
        'error',
        { patterns: [RELATIVE_PARENT_PATTERN, PUBLIC_API_ONLY_PATTERN] },
      ],
    },
  },

  // Each module may import its OWN internals via the alias, but is still
  // forbidden from reaching into sibling modules (horizontal imports).
  ...MODULES.map((name) => ({
    files: [`src/modules/${name}/**/*.{js,vue}`],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            RELATIVE_PARENT_PATTERN,
            {
              group: ['@/modules/*/*', '@/modules/*/**', `!@/modules/${name}/**`],
              message: `Horizontal import violation: "${name}" may only use other modules through their Public API ("@/modules/<name>").`,
            },
          ],
        },
      ],
    },
  })),

  // core/ is module-agnostic: importing ANYTHING from src/modules/ is fatal…
  {
    files: ['src/core/**/*.{js,vue}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            RELATIVE_PARENT_PATTERN,
            {
              group: ['@/modules/**'],
              message:
                'Downward import violation: src/core/ must not import business logic from src/modules/.',
            },
          ],
        },
      ],
    },
  },

  // …except the main router, which aggregates module route arrays strictly
  // through each module's Public API (index.js).
  {
    files: ['src/core/router/**/*.js'],
    rules: {
      'no-restricted-imports': [
        'error',
        { patterns: [RELATIVE_PARENT_PATTERN, PUBLIC_API_ONLY_PATTERN] },
      ],
    },
  },
]
