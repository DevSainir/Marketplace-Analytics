/**
 * End-to-end: the authentication journey.
 *
 * Deliberately short. Login is already covered by a component test at the HTTP
 * boundary and an integration test across the store; what only a browser can
 * show is that the HttpOnly refresh cookie is really set by the server, really
 * survives a reload, and really keeps the router guard from bouncing the user
 * to /login on their next visit — none of which exists outside a real browser
 * with a real cookie jar.
 */
import {
  AFTER_LOGIN_PATH,
  CREDENTIALS,
  expect,
  signIn,
  test,
} from "../fixtures/app.js";

test("a guest visiting a protected page is sent to login and returned afterwards", async ({
  page,
}) => {
  await page.goto("/monitoring");

  await expect(page).toHaveURL(/\/login\?redirect=/);
  expect(new URL(page.url()).searchParams.get("redirect")).toBe("/monitoring");

  await page.getByPlaceholder("manager@company.ru").fill(CREDENTIALS.email);
  await page.getByPlaceholder("••••••••").fill(CREDENTIALS.password);
  await page.getByRole("button", { name: "Войти" }).click();

  await expect(page).toHaveURL(/\/monitoring$/);
});

test("wrong credentials keep the user on the form with a message", async ({
  page,
}) => {
  await page.goto("/login");

  await page.getByPlaceholder("manager@company.ru").fill(CREDENTIALS.email);
  await page.getByPlaceholder("••••••••").fill("definitely-not-the-password");
  await page.getByRole("button", { name: "Войти" }).click();

  await expect(
    page.getByText(/Invalid email or password|Неверн/i),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});

test("the session survives a full page reload", async ({ signedIn: page }) => {
  // This is the whole reason the refresh token is an HttpOnly cookie rather
  // than something the SPA holds: a reload wipes every bit of in-memory state,
  // and the user must still be logged in.
  await page.reload();

  await expect(page).toHaveURL(new RegExp(`${AFTER_LOGIN_PATH}$`));
  // The profile link is the header's authenticated-only affordance, and unlike
  // the nav links it is not hidden behind the burger menu.
  await expect(page.getByLabel("Профиль")).toBeVisible();
});

test("the refresh cookie is HttpOnly and scoped to the auth path", async ({
  page,
}, testInfo) => {
  // Asserted from the browser's own cookie jar, which is the only place the
  // real flags can be observed. Without HttpOnly a single XSS owns the session
  // for seven days.
  // `testInfo` is not decoration: without it `logInThroughForm` cannot extend
  // this test's budget before waiting out a rate-limit window, and a 65-second
  // wait inside a 60-second timeout can only fail. It bites whenever another
  // spec fails and its retries burn the login allowance — which is how one red
  // test turned into two on 2026-09-05.
  await signIn(page, testInfo);

  const cookies = await page.context().cookies();
  const refresh = cookies.find((cookie) => cookie.name === "refresh_token");

  expect(refresh, "no refresh cookie was set by the server").toBeDefined();
  expect(refresh.httpOnly).toBe(true);
  expect(refresh.path).toContain("/auth");
  expect(refresh.sameSite).toBe("Lax");
});

test("logging out ends the session for good", async ({ signedIn: page }) => {
  // Straight to the control: `ui-next` replaced the burger with a header that
  // carries its nav, the profile link and this button at every viewport, so
  // there is no longer a menu to open first.
  await page.getByRole("button", { name: "Выйти" }).click();

  await expect(page).toHaveURL(/\/login/);

  // Going back to a protected page must not restore the session from a stale
  // cookie the server has already revoked.
  await page.goto("/monitoring");
  await expect(page).toHaveURL(/\/login/);
});
