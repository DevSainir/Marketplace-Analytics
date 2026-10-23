/**
 * Shared end-to-end fixtures.
 *
 * The `signedIn` fixture logs in through the real form rather than injecting a
 * token. That costs a few seconds, and it is the point: the login form, the
 * HttpOnly refresh cookie, the router guard and the workspace bootstrap are
 * exactly the chain these tests exist to protect, and a seeded token would skip
 * all four.
 *
 * **Why not reuse `storageState` across tests.** The obvious optimisation —
 * log in once per worker and replay the storage state — is unsafe against this
 * backend. Every app bootstrap rotates the refresh cookie, so a second context
 * presenting the same cookie is a *replay*, which the breach detector correctly
 * answers by revoking every session for that account. One login per test is the
 * price of testing rotation honestly.
 *
 * That makes the auth rate limiter (10 attempts / 60 s per IP) a real
 * constraint on this tier, so `logInThroughForm` waits the window out and
 * retries once rather than reporting a throttle as a login failure.
 */
import { expect, test as base } from "@playwright/test";

/** Credentials of the seeded end-to-end account. */
export const CREDENTIALS = {
  email: process.env.E2E_EMAIL || "dev-preview@example.com",
  password: process.env.E2E_PASSWORD || "dev-preview-password",
};

/** Where a successful login lands. */
export const AFTER_LOGIN_PATH = "/monitoring";

/** The backend's auth rate-limit window, in seconds (AUTH_RATE_LIMIT_WINDOW_SECONDS). */
const RATE_LIMIT_WINDOW_SECONDS = Number(
  process.env.E2E_RATE_LIMIT_WINDOW_SECONDS || 60,
);

/**
 * Submit the login form once and report whether the session started.
 *
 * @param {import('@playwright/test').Page} page
 * @returns {Promise<'ok' | 'throttled' | 'rejected'>}
 */
async function submitLogin(page) {
  await page.goto("/login");
  await page.getByPlaceholder("manager@company.com").fill(CREDENTIALS.email);
  await page.getByPlaceholder("••••••••").fill(CREDENTIALS.password);
  await page.getByRole("button", { name: "Continue" }).click();

  const landed = await page
    .waitForURL(new RegExp(`${AFTER_LOGIN_PATH}$`), { timeout: 15_000 })
    .then(() => true)
    .catch(() => false);
  if (landed) return "ok";

  const message = await page
    .locator("form p")
    .first()
    .textContent()
    .catch(() => "");
  return /too many requests/i.test(message || "")
    ? "throttled"
    : "rejected";
}

/**
 * Log in through the real form, waiting out the rate limiter if it engages.
 *
 * @param {import('@playwright/test').Page} page
 * @param {import('@playwright/test').TestInfo} [testInfo] used to extend the
 *   timeout only when a throttle wait is actually needed.
 */
export async function logInThroughForm(page, testInfo) {
  const first = await submitLogin(page);
  if (first === "ok") return;

  expect(
    first,
    `Login was rejected for ${CREDENTIALS.email}. Seed the account or set E2E_EMAIL / E2E_PASSWORD.`,
  ).toBe("throttled");

  // Only pay for the extra time on the path that needs it — and refuse to wait
  // at all when the budget cannot be extended. Without `testInfo` this would
  // sleep 65 seconds inside a 60-second timeout and fail with a timeout that
  // says nothing about the throttling that caused it.
  expect(
    testInfo,
    "logInThroughForm needs testInfo to wait out a rate-limit window; pass it from the test",
  ).toBeDefined();
  testInfo.setTimeout(
    testInfo.timeout + (RATE_LIMIT_WINDOW_SECONDS + 15) * 1000,
  );
  await page.waitForTimeout((RATE_LIMIT_WINDOW_SECONDS + 5) * 1000);

  expect(
    await submitLogin(page),
    "Login was still throttled after waiting a full rate-limit window.",
  ).toBe("ok");
}

/** Backwards-compatible alias for specs that log in explicitly. */
export const signIn = logInThroughForm;

export const test = base.extend({
  /**
   * A page that is already authenticated.
   *
   * Fails with a setup hint rather than a cryptic timeout when the environment
   * has no seeded account — the most common reason this tier is red on a fresh
   * machine.
   */
  signedIn: async ({ page }, use, testInfo) => {
    await page.goto("/login");
    await expect(
      page.getByRole("heading", { name: "Sign in to your account" }),
      "The app did not serve /login. Is the stack up and E2E_BASE_URL correct?",
    ).toBeVisible();

    await logInThroughForm(page, testInfo);

    await use(page);
  },
});

export { expect };
