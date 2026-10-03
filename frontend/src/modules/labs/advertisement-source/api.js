/**
 * Where the lab's numbers come from: the finmodel's static datapack.
 *
 * The same file `/labs/finmodel` reads — one copy of «Демо»'s window
 * (P&L 15.07–06.09.2026) rather than a second one that could drift from it.
 * It is a static asset, not our API, so this is a bare `fetch` and not the
 * Axios client: that one carries `/api` as its base and the workspace header,
 * neither of which a file in `public/` wants.
 *
 * When the block moves into the product this file is what gets replaced — by
 * a real endpoint — and nothing above it should need to know.
 */
const DATAPACK_URL = '/data/finmodel-datapack.json'

/** @returns {Promise<object>} the parsed datapack; throws on a non-2xx. */
export async function fetchAdsDatapack() {
  const response = await fetch(DATAPACK_URL)
  if (!response.ok) throw new Error(`датапак не загрузился (${response.status})`)
  return response.json()
}
