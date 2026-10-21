/**
 * Survive a deploy in a tab that was open across it.
 *
 * A deploy replaces every asset with a freshly hashed name, so a tab that has
 * been open across one asks for chunks that no longer exist and dies on the
 * next lazy route. One full page load fixes it — but it has to load the page
 * the person was GOING to. Reloading the current URL, which this used to do,
 * fetched the new build and left them exactly where they clicked from: "it
 * loads something, refreshes, but ends up on the page I started from". Vite
 * reports the missing chunk as `vite:preloadError` before the router sees
 * anything, so the target has to be remembered from the navigation itself.
 *
 * A flag in sessionStorage makes sure a genuinely broken build cannot turn this
 * into an infinite reload loop; a successful navigation clears it, so the next
 * deploy gets its own single reload. When the flag is already set the error is
 * left to propagate rather than swallowed: the navigation fails visibly in the
 * console instead of being cancelled in silence.
 */
export const RELOADED_FOR_STALE_ASSETS = 'reloaded-for-stale-assets'

const CHUNK_LOAD_ERROR =
  /dynamically imported module|Importing a module script failed|Failed to fetch|Unable to preload CSS/i

export function installStaleAssetReload(
  router,
  { storage = window.sessionStorage, location = window.location, events = window } = {},
) {
  // The navigation in flight, if any: where a reload has to land.
  let pending = null

  router.beforeEach((to) => {
    pending = to
  })
  router.afterEach(() => {
    pending = null
    storage.removeItem(RELOADED_FOR_STALE_ASSETS)
  })

  /** Load `to` (or the current page) from scratch; false once already tried. */
  function reloadOnce(to) {
    if (storage.getItem(RELOADED_FOR_STALE_ASSETS)) return false
    storage.setItem(RELOADED_FOR_STALE_ASSETS, '1')
    if (to) location.assign(router.resolve(to).href)
    else location.reload() // a lazy piece of the current page, not a navigation
    return true
  }

  events.addEventListener('vite:preloadError', (event) => {
    if (reloadOnce(pending)) event.preventDefault()
  })

  router.onError((error, to) => {
    pending = null
    if (CHUNK_LOAD_ERROR.test(String(error?.message))) reloadOnce(to)
  })
}
