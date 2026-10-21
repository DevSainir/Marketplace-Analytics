/**
 * The heatmap's settings, remembered for an hour.
 *
 * A back-and-forward to another page, or a reload, used to drop every choice —
 * metrics, cut, filters, sort — back to the defaults. So they are kept in this
 * browser's `localStorage`, keyed by workspace (an article filter means nothing
 * in another one), and forgotten an hour after the last change: the same hour
 * the period is kept for (`core/utils/periodMemory.js`, where the period itself
 * now lives), so the page never comes back with half its choices.
 *
 * Storage can be blocked or empty (a private window, cleared site data), so
 * every access is guarded and the page simply starts on its defaults.
 */
import { getWorkspaceId } from '@/core/api/axios'

const TTL_MS = 60 * 60 * 1000

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
