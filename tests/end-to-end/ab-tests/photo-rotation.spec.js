/**
 * End-to-end: creating an A/Б test and putting photos into its rotation.
 *
 * This journey earns a browser test because its failure makes the feature
 * unusable in a way no lower tier can see: the upload is a real multipart form
 * post from a real file input, and the picture the table renders comes back
 * from our own image route rather than from WB. A broken content type, a
 * mis-built FormData or a wrong image URL all pass every unit and component
 * test and leave the user looking at broken thumbnails.
 *
 * What is deliberately NOT here: the rotation itself. Advancing a test needs
 * 10 000 advertising impressions and a WB media upload against a live seller
 * card — that is pinned by the runner's unit tests, and driving it from a
 * browser would mean rewriting a real storefront.
 */
import { expect, test } from '../fixtures/app.js'

/** A minimal valid JPEG — enough bytes for the upload to be a real file. */
const JPEG = Buffer.concat([
  Buffer.from([0xff, 0xd8, 0xff, 0xe0]),
  Buffer.alloc(2048, 0x20),
  Buffer.from([0xff, 0xd9]),
])

test('a test is created, takes photos, and shows them as rows of the result table', async ({
  signedIn: page,
}) => {
  const name = `E2E ротация ${Date.now()}`

  await page.goto('/ab-tests')
  await expect(page.getByRole('heading', { name: 'A/Б-тесты' })).toBeVisible()

  await page.getByTestId('new-test').click()
  await page.getByTestId('test-name').fill(name)
  await page.getByTestId('test-nm-id').fill('995716075')
  await page.getByTestId('create-test').click()

  // Creating navigates straight to the detail page — the next thing to do is
  // always "add photos", so the list would just be a stop on the way.
  await expect(page.getByRole('heading', { name })).toBeVisible({ timeout: 15_000 })

  await page.getByTestId('upload').setInputFiles([
    { name: 'variant-1.jpg', mimeType: 'image/jpeg', buffer: JPEG },
    { name: 'variant-2.jpg', mimeType: 'image/jpeg', buffer: JPEG },
  ])

  // Photos are ROWS here, not the two fixed columns WB's own screen uses: a
  // rotation runs up to ten, and the metrics are the columns.
  const rows = page.getByTestId('variant-row')
  await expect(rows).toHaveCount(2, { timeout: 30_000 })

  // The thumbnail is served by our own image route. A queued variant has no WB
  // URL at all, so this is the only place the picture can come from.
  const thumbnail = rows.first().getByRole('img').first()
  await expect(thumbnail).toBeVisible()
  const source = await thumbnail.getAttribute('src')
  expect(source).toMatch(/\/api\/ab-tests\/.+\/variants\/.+\/image$/)

  const response = await page.request.get(source)
  expect(response.status()).toBe(200)
  expect(response.headers()['content-type']).toContain('image')

  // Nothing has been live yet, so every ratio reads «—». Zero would claim the
  // photo converted nobody, which is a measurement it has not made.
  await expect(page.getByTestId('ctr').first()).toHaveText('—')

  // Search covers the whole row from one box — here, the test's own name.
  await page.goto('/ab-tests')
  await page.getByTestId('search').fill(name)
  await expect(page.getByTestId('test-link')).toHaveCount(1, { timeout: 15_000 })
  await expect(page.getByTestId('test-link')).toContainText(name)
})

test('the A/Б-tests page is behind the auth guard', async ({ page }) => {
  // A test names a card and rewrites its main photo; an unauthenticated reader
  // must not reach either the list or the images.
  await page.goto('/ab-tests')

  await expect(page).toHaveURL(/\/login/)
})
