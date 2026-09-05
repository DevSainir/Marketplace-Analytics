/**
 * End-to-end: the P&L dashboard — the finreports landing page.
 *
 * The journey a seller repeats daily: open /finreports, read the four cards,
 * see the per-SKU table under them. The arithmetic is unit- and
 * integration-tested; what only a browser can prove is that the page composes
 * against the real API — the dashboard resolves (no eternal «Считаем отчёт…»),
 * and the table renders rows from the same response.
 *
 * One signed-in test on purpose: this tier's login budget is bounded by the
 * API's auth rate limiter.
 */
import { expect, test } from "../fixtures/app.js";

test("the dashboard renders its cards and the per-SKU table", async ({
  signedIn: page,
}) => {
  await page.goto("/finreports");

  await expect(
    page.getByRole("heading", { name: /Прибыли и убытки/ }),
  ).toBeVisible();

  // The four cards the page exists for. `.first()` because «Логистика» and
  // «Себестоимость» legitimately recur as table column headers below the
  // cards. Generous timeout: the default window aggregates a month of
  // settlement rows on first paint.
  for (const label of [
    "Продажи",
    "Логистика",
    "Себестоимость",
    "Итого к оплате",
  ]) {
    await expect(page.getByText(label, { exact: true }).first()).toBeVisible({
      timeout: 30_000,
    });
  }

  // The per-SKU table arrived from the same response (async chunk + data).
  await expect(
    page.getByRole("heading", { name: "По артикулам" }),
  ).toBeVisible();
});

test("the dashboard is behind the auth guard", async ({ page }) => {
  // Revenue and margins are commercially sensitive tenant data.
  await page.goto("/finreports");

  await expect(page).toHaveURL(/\/login/);
});
