/**
 * End-to-end: creating an A/B test and putting photos into its rotation.
 *
 * This journey earns a browser test because its failure makes the feature
 * unusable in a way no lower tier can see: the upload is a real multipart form
 * post from a real file input, and the picture the table renders comes back
 * from our own image route rather than from WB. A broken content type, a
 * mis-built FormData or a wrong image URL all pass every unit and component
 * test and leave the user looking at broken thumbnails.
 *
 * What is deliberately NOT here: the rotation itself. Advancing a test needs
 * real advertising traffic and a WB media upload against a live seller card —
 * that is pinned by the runner's unit tests, and driving it from a browser
 * would mean rewriting a real storefront.
 */
import { expect, test } from "../fixtures/app.js";

/**
 * A real, decodable 1x1 baseline JPEG.
 *
 * It has to be decodable, not merely JPEG-shaped: the assertion below is that
 * the browser actually RENDERED the thumbnail, and `naturalWidth` stays 0 for
 * bytes it cannot decode. The previous fixture — two markers around a block of
 * spaces — passed upload (the server checks the declared type and the size, it
 * does not decode) but could never have produced a picture on screen.
 */
const JPEG = Buffer.from(
  "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a" +
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAHwAAAQUBAQEB" +
    "AQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1Fh" +
    "ByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZ" +
    "WmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXG" +
    "x8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9oACAEBAAA/APn+v//Z",
  "base64",
);

test("a test is created, takes photos, and shows them as columns of the result table", async ({
  signedIn: page,
}) => {
  const name = `E2E ротация ${Date.now()}`;

  await page.goto("/ab-tests");
  await expect(page.getByRole("heading", { name: "A/Б-тесты" })).toBeVisible();

  await page.getByTestId("new-test").click();
  await page.getByTestId("test-name").fill(name);
  // The article is picked from the workspace's catalogue, never typed: a
  // free-text field let a test be created against article `1`, which nothing
  // downstream could rotate, advertise, or upload a photo to.
  await page.getByTestId("sku-search").click();
  await page.getByTestId("sku-search").fill("995716075");
  await page.getByTestId("sku-option").first().click();
  await expect(page.getByTestId("picked-sku")).toContainText("995716075");

  // A single-bound mode sends only the bound it reads: the API refuses a body
  // carrying the other one, so a form that rendered both fields here would 422
  // on every submit. («Показы и время» is the mode that shows both, and the
  // one the unit tier covers.)
  await page.getByTestId("trigger-mode").selectOption("time");
  await expect(page.getByTestId("slot-minutes")).toBeVisible();
  await expect(page.getByTestId("impression-budget")).toHaveCount(0);
  await page.getByTestId("slot-minutes").fill("30");

  await page.getByTestId("create-test").click();

  // Creating navigates straight to the detail page — the next thing to do is
  // always "add photos", so the list would just be a stop on the way.
  await expect(page.getByRole("heading", { name })).toBeVisible({
    timeout: 15_000,
  });

  // The detail page reports the trigger that is actually in force, not both.
  await expect(page.getByText("Смена фото каждые 30 мин")).toBeVisible();

  await page.getByTestId("upload").setInputFiles([
    { name: "variant-1.jpg", mimeType: "image/jpeg", buffer: JPEG },
    { name: "variant-2.jpg", mimeType: "image/jpeg", buffer: JPEG },
  ]);

  // Photos are COLUMNS and metrics are rows. Every row of the table is a
  // comparison across photos, and a comparison reads along a line — «Показов»
  // as a row puts the numbers side by side instead of ten rows apart. The width
  // that costs is paid for with one horizontal scroll inside the card.
  //
  // Two columns for two uploads. A workspace with a WB token would carry a
  // third — the card's own photo, enrolled at creation — but this one has
  // pasted no credentials, and creating a test deliberately does not require
  // them. That is the case being exercised here as well.
  const columns = page.getByTestId("variant-column");
  await expect(columns).toHaveCount(2, { timeout: 30_000 });

  // The thumbnail is served by our own image route. A queued variant has no WB
  // URL at all, so this is the only place the picture can come from.
  //
  // It reaches the tag as an object URL, NOT as `/api/…/image`. This assertion
  // used to require the latter, which cannot work: that route is
  // authenticated, and the access token lives in memory, so an `<img>` loading
  // it directly sends neither the token nor the workspace header and is
  // answered 401. The SPA fetches the bytes through the API client instead and
  // hands `<img>` a blob — the same route the finreports downloads take. What
  // is worth pinning is unchanged and asserted below: a picture arrived, and
  // its bytes came from our own store rather than from WB.
  const thumbnail = columns.first().getByRole("img").first();
  await expect(thumbnail).toBeVisible();
  const source = await thumbnail.getAttribute("src");
  expect(source).toMatch(/^blob:/);

  // `naturalWidth` is 0 until the browser has actually decoded bytes behind
  // that URL, so this is what separates a rendered photo from an `<img>` that
  // merely exists with a plausible src.
  await expect
    .poll(
      () =>
        thumbnail.evaluate((node) => node.complete && node.naturalWidth > 0),
      {
        timeout: 15_000,
      },
    )
    .toBe(true);

  // Nothing has been live yet, so every ratio reads «—». Zero would claim the
  // photo converted nobody, which is a measurement it has not made.
  await expect(page.getByTestId("ctr").first()).toHaveText("—");

  // Search covers the whole row from one box — here, the test's own name.
  await page.goto("/ab-tests");
  await page.getByTestId("search").fill(name);
  await expect(page.getByTestId("test-link")).toHaveCount(1, {
    timeout: 15_000,
  });
  await expect(page.getByTestId("test-link")).toContainText(name);
});

test("the A/Б-tests page is behind the auth guard", async ({ page }) => {
  // A test names a card and rewrites its main photo; an unauthenticated reader
  // must not reach either the list or the images.
  await page.goto("/ab-tests");

  await expect(page).toHaveURL(/\/login/);
});
