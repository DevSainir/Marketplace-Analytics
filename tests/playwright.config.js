/**
 * Playwright configuration for the two browser-driven tiers.
 *
 * Lives beside the tests it runs (with their `package.json`) so the repository
 * root stays free of tooling files. Every path below is relative to THIS file.
 *
 * The end-to-end tests are the slowest and most brittle in the pyramid, so
 * there are deliberately few of them: they cover the handful of journeys where
 * a break means the product is unusable, and nothing else. Everything a cheaper
 * tier can prove is proven there instead.
 *
 * They run against a REAL stack — a real API, a real database, a real browser.
 * Nothing is mocked, because a mocked end-to-end test is just a slow
 * integration test.
 *
 * Point them at an environment with `E2E_BASE_URL` (default: the Vite dev
 * server) and give them an account with `E2E_EMAIL` / `E2E_PASSWORD`.
 */
import { defineConfig, devices } from '@playwright/test'

const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:5173'

export default defineConfig({
  // Both browser-driven tiers share this runner; each project names its own
  // directory so `--project` selects a tier.
  outputDir: './.artifacts',

  // ONE worker, everywhere. Not for the runner's sake: these tests share one
  // backend and one seeded account, and parallel logins rotate each other's
  // refresh cookies, which the backend correctly reads as token reuse and
  // answers by revoking every session.
  workers: 1,
  fullyParallel: false,

  // Flakiness is a bug in an end-to-end test, not a fact of life. One retry in
  // CI absorbs genuine infrastructure noise; `forbidOnly` stops a `.only` from
  // silently reducing the suite to one test.
  retries: process.env.CI ? 1 : 0,
  forbidOnly: !!process.env.CI,

  // Generous but finite: a hung request must fail the test, never hang the
  // pipeline.
  timeout: 60_000,
  expect: { timeout: 10_000 },

  reporter: process.env.CI
    ? [['github'], ['html', { outputFolder: './.report', open: 'never' }]]
    : [['list'], ['html', { outputFolder: './.report', open: 'never' }]],

  use: {
    baseURL: BASE_URL,
    launchOptions: {
      // Chromium's shared-memory segment defaults to 64 MB on a trimmed host;
      // exhausting it kills tabs as "Target closed", which reads as a flaky
      // test rather than as the memory pressure it is. Writing that buffer to
      // /tmp costs a little speed and removes the need for the memory.
      //
      // The rest keep the browser to what the tests need: no GPU process, no
      // extensions, and nothing running in the background between tests. The
      // heap cap is the backstop for a runaway renderer — Chromium is a child
      // of the test process, so it would otherwise be bounded only by the box
      // the stack under test shares with it.
      args: [
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--disable-extensions',
        '--disable-background-networking',
        '--disable-background-timer-throttling',
        '--disable-renderer-backgrounding',
        '--js-flags=--max-old-space-size=256',
      ],
    },
    // Evidence only for failures: traces and video on every run would make the
    // artifacts larger than the repository.
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    locale: 'ru-RU',
    timezoneId: 'Europe/Moscow',
  },

  projects: [
    {
      // The end-to-end tier: real journeys against a real stack.
      name: 'chromium',
      testDir: './end-to-end',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      // The browser half of the performance tier: the "app loads forever"
      // failure mode, driven by intercepting the network rather than by load.
      // Kept out of the default run because it deliberately breaks the API.
      name: 'frontend-performance',
      testDir: './performance/frontend',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
