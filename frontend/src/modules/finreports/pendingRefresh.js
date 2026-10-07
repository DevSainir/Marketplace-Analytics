/**
 * The «Обновить» click as it survives a page reload.
 *
 * Reloading mid-refresh used to put an enabled button back over a run that was
 * still going. Reading the harvest lock on load fixed the middle of that, but
 * only the middle: the lock is held by the **task**, and the task is not the
 * click. Between the POST returning and the worker picking the job up nothing
 * holds the lock, and after the task ends nothing holds it either — yet in both
 * windows the seller is still waiting for the refresh they asked for. A reload
 * landing in either one found `running: false` and dropped the state, which is
 * exactly what "reloading still kills it" looks like.
 *
 * So the click is written down. This file is the note: which task, when it was
 * asked for, and how far the settlement history reached at that moment — the
 * last one because "did a new week arrive?" is a comparison against the moment
 * of the click, and a reload has otherwise forgotten what that was.
 *
 * Split out of the store for the reason the period memory is (`core/utils/
 * periodMemory.js`): the store keeps the refs, this keeps the memory, and how long a note stays true is its own
 * decision rather than a line buried in a poll loop.
 */

/** Where the pending refresh lives between page loads. */
const PENDING_KEY = 'finreports:pending-refresh'

/**
 * How long a note outlives the click.
 *
 * The poll gives up after twenty minutes and says the run continues in the
 * background, so a note older than that describes a refresh the page has
 * already stopped claiming to watch. Past it the button must come back — a
 * worker that died mid-task holds no lock and finishes nothing, and a
 * permanently disabled «Обновить» would be a worse failure than the one this
 * file exists to fix.
 */
const PENDING_TTL_MS = 20 * 60 * 1000

/**
 * The pending refresh, or `null` when there is none or it no longer counts.
 *
 * An expired note is removed on the way out, so a tab reopened the next morning
 * is not carrying yesterday's click around.
 *
 * @returns {{task_id: ?string, settled_before: string, asked_at: string}|null}
 */
export function readPendingRefresh() {
  try {
    const pending = JSON.parse(localStorage.getItem(PENDING_KEY) ?? 'null')
    const askedAt = Date.parse(pending?.asked_at ?? '')
    if (!askedAt) return null
    if (Date.now() - askedAt > PENDING_TTL_MS) {
      localStorage.removeItem(PENDING_KEY)
      return null
    }
    return pending
  } catch {
    return null
  }
}

/**
 * Write down a refresh that has been asked for and not yet resolved.
 *
 * @param {?string} taskId Celery id of the enqueued harvest, when there is one.
 * @param {string} settledBefore Settlement day on screen at the click.
 */
export function writePendingRefresh(taskId, settledBefore) {
  try {
    localStorage.setItem(
      PENDING_KEY,
      JSON.stringify({
        task_id: taskId ?? null,
        settled_before: settledBefore ?? '',
        asked_at: new Date().toISOString(),
      }),
    )
  } catch {
    /* private mode / storage disabled — the refresh just won't survive a reload */
  }
}

/** Forget the pending refresh, once it has been resolved or abandoned. */
export function clearPendingRefresh() {
  try {
    localStorage.removeItem(PENDING_KEY)
  } catch {
    /* nothing to clear if storage is unavailable */
  }
}
