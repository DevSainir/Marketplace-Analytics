/**
 * The heatmap's settings, remembered for twenty minutes.
 *
 * A back-and-forward to another page, or a reload, used to drop every choice —
 * window, metrics, cut, filters, sort — back to the defaults. So they are kept
 * in this browser's `localStorage`, keyed by кабинет (an article filter means
 * nothing in another one), and forgotten twenty minutes after the last change:
 * long enough to survive a detour, short enough that tomorrow opens on
 * yesterday-ending-yesterday rather than on a stale window.
 *
 * Storage can be blocked or empty (a private window, cleared site data), so
 * every access is guarded and the page simply starts on its defaults.
 */
import { getWorkspaceId } from '@/core/api/axios'

const TTL_MS = 20 * 60 * 1000

const keyOf = () => `heatmap:settings:${getWorkspaceId() ?? 'none'}`

/** @returns {object|null} The remembered settings, or `null` when none are fresh. */
export function recallSettings() {
  try {
    const raw = localStorage.getItem(keyOf())
    if (!raw) return null
    const { at, settings } = JSON.parse(raw)
    return Date.now() - at < TTL_MS ? settings : null
  } catch {
    return null
  }
}

/** @param {object} settings Plain, JSON-safe values only. */
export function rememberSettings(settings) {
  try {
    localStorage.setItem(keyOf(), JSON.stringify({ at: Date.now(), settings }))
  } catch {
    // Storage refused: the page still works, it just will not remember.
  }
}
