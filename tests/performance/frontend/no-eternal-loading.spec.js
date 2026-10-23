/**
 * Playwright: the SPA must never load forever.
 *
 * This is the failure the team actually experienced — the API stopped
 * answering, and the app rendered its header over a permanently blank page.
 * Nothing crashed, nothing logged, and it read as "the frontend is broken".
 *
 * The defence is that no request may hang: the axios client carries a 15 s
 * timeout, the auth store treats a timeout as transient and then gives up, and
 * the router guard's bootstrap is bounded. These tests assert the *observable*
 * consequence — under a dead or glacial backend the app resolves to a usable
 * screen instead of a spinner nobody can escape.
 *
 * **Route pattern matters here.** Only `**​/api/v1/**` may be intercepted, never
 * `**​/api/**`: in dev the Vite server serves the app's own source over HTTP, and
 * `/src/core/api/axios.js` matches the broader glob. Blocking that stops the
 * SPA from booting at all, which looks exactly like the bug under test and is
 * not it.
 *
 * Run:
 *   npx playwright test --project=frontend-performance
 */
import { expect, test } from '@playwright/test'

/** Only the backend API — never the dev server's module URLs. */
const API_ROUTES = '**/api/v1/**'

/**
 * Budget for a backend that refuses connections outright.
 * Measured: ~3.1 s — three bootstrap attempts, each failing instantly, with
 * 0.4 s + 1 s between them.
 */
const DEAD_BACKEND_BUDGET_MS = 10_000

/**
 * Budget for a backend that accepts the connection and never answers — the
 * nastier case, because only a client-side timeout can break it.
 *
 * Measured: ~12 s. That is the full bootstrap ladder at the auth surface's own
 * timeout: 3 s, then 0.4 s, 3 s, 1 s, 3 s, before the store gives up and the
 * guard routes to /login.
 *
 * It used to be ~50 s, because /refresh shared the 15 s budget meant for the
 * finreports report. The knobs, if this ever needs to shrink further, are
 * `AUTH_TIMEOUT_MS` in the axios client and `BOOTSTRAP_RETRY_DELAYS_MS` in the
 * auth store — and this budget is the test that will hold the new value. Note
 * the floor: two retries exist so a backend restarting mid-deploy does not log
 * everyone out, and dropping them buys speed at that cost.
 */
const HANGING_BACKEND_BUDGET_MS = 20_000

test('a dead backend resolves to the login screen, not an endless spinner', async ({ page }) => {
  await page.route(API_ROUTES, (route) => route.abort('connectionrefused'))

  await page.goto('/monitoring', { waitUntil: 'domcontentloaded' })

  // The guard must reach a decision — guest — and route accordingly.
  await expect(page).toHaveURL(/\/login/, { timeout: DEAD_BACKEND_BUDGET_MS })
  await expect(page.getByRole('heading', { name: 'Sign in to your account' })).toBeVisible()
})

test('a hanging backend still resolves within the client timeout', async ({ page }) => {
  await page.route(API_ROUTES, async () => {
    // Deliberately never fulfilled: the server accepted the connection and
    // will never answer.
    await new Promise(() => {})
  })

  // `domcontentloaded`, not the default `load`: a permanently pending request
  // would otherwise hold the navigation open and time out the goto itself.
  await page.goto('/monitoring', { waitUntil: 'domcontentloaded' })

  await expect(page).toHaveURL(/\/login/, { timeout: HANGING_BACKEND_BUDGET_MS })
})

test('a 500 from the session bootstrap does not strand the app', async ({ page }) => {
  // An empty-body 500 on the auth surface is the signature of the host running
  // out of disk (the Docker VM goes read-only and the Vite proxy fabricates the
  // 500). The app must still render something a person can act on.
  await page.route('**/api/v1/auth/refresh', (route) => route.fulfill({ status: 500, body: '' }))

  await page.goto('/monitoring', { waitUntil: 'domcontentloaded' })

  await expect(page).toHaveURL(/\/login/, { timeout: DEAD_BACKEND_BUDGET_MS })
})

test('the first paint is not blocked behind the session request', async ({ page }) => {
  // Chrome and header must be on screen while the session resolves. A blank
  // document until the API answers is what makes a slow backend look like a
  // broken frontend — and with the hanging-backend budget above, that would be
  // fifty seconds of white screen.
  await page.route(API_ROUTES, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 5_000))
    await route.abort('connectionrefused')
  })

  await page.goto('/monitoring', { waitUntil: 'domcontentloaded' })

  await expect(page.locator('header')).toBeVisible({ timeout: 5_000 })
})
