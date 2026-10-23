/**
 * End-to-end: the monitoring journey the team performs every morning.
 *
 * open → log in → monitoring → switch workspace → search a SKU.
 *
 * This is the one flow whose breakage makes the product unusable, so it is the
 * one flow that earns a browser test. Each step crosses a boundary that no
 * cheaper tier spans: the router guard resolving a real session, the workspace
 * selection reaching `localStorage` and then the `X-Workspace-Id` header on a
 * real XHR, and the SKU search round-tripping to a real database.
 *
 * Split into two tests rather than one long script so a failure names which
 * half of the flow broke.
 */
import { expect, test } from "../fixtures/app.js";

test("monitoring loads and a SKU can be found by vendor code", async ({
  signedIn: page,
}) => {
  await expect(
    page.getByRole("heading", { name: "SKU monitoring" }),
  ).toBeAttached();

  const search = page.getByRole("combobox");
  await expect(search).toBeVisible();

  await search.click();
  await search.fill("M-");

  // The results come from the real catalogue, so this also proves the request
  // carried a workspace the account can actually read.
  const options = page.getByRole("option");
  await expect(options.first()).toBeVisible({ timeout: 15_000 });

  await options.first().click();
  await expect(search).not.toHaveValue("M-");
});

test("switching workspace re-scopes every subsequent request", async ({
  signedIn: page,
}) => {
  await page.goto("/profile");
  await expect(
    page.getByRole("heading", { name: "Workspaces" }),
  ).toBeVisible();

  const before = await page.evaluate(() =>
    localStorage.getItem("workspace:id"),
  );
  expect(before, "no workspace was selected after login").toBeTruthy();

  const otherWorkspace = page.getByRole("button", { name: /^Select/ }).first();
  if (!(await otherWorkspace.isVisible().catch(() => false))) {
    test.skip(
      true,
      "Only one workspace in this environment; nothing to switch to.",
    );
  }

  await otherWorkspace.click();

  // Switching RELOADS this page; it no longer redirects to /monitoring. The
  // reload is what drops every per-workspace cache — the destination was
  // incidental, and sending everyone to Monitoring put a manager not granted it
  // on "No access to this section" for the crime of changing workspace.
  await expect(page).toHaveURL(/\/profile$/);

  const after = await page.evaluate(() => localStorage.getItem("workspace:id"));
  expect(after).not.toBe(before);

  // The assertion that matters: the new tenant reaches the wire, and survives a
  // navigation. A switch that updated only the UI would show the previous
  // tenant's numbers under the new workspace's name; a selection that did not
  // persist would silently drop the user back into the first workspace.
  const [request] = await Promise.all([
    page.waitForRequest((r) => r.url().includes("/api/v1/monitoring/")),
    page.goto("/monitoring"),
  ]);
  expect(request.headers()["x-workspace-id"]).toBe(after);
  expect(await page.evaluate(() => localStorage.getItem("workspace:id"))).toBe(
    after,
  );
});

test("an unknown route renders the 404 page, not a blank app", async ({
  signedIn: page,
}) => {
  // A blank page on a mistyped URL reads as "the app is down".
  await page.goto("/no-such-page");

  await expect(page.getByText(/page not found/i)).toBeVisible();
});
