/**
 * The per-size drill-down's cache: nm_id -> { loading, error, data }.
 *
 * Split out of the store for two reasons. The store had reached 499 of its
 * 500 lines. And this is the part that went wrong: a request overtaken by a
 * change of period returned early and left its entry at `loading: true`, and
 * since a loading entry is never asked for again, that row spun its
 * "Loading…" until the page was reloaded.
 *
 * So staleness is decided by a generation counter rather than by comparing
 * dates after the fact. `reset()` bumps it and empties the cache in one step,
 * which means no entry can outlive the window it was fetched for — and a
 * response from an older generation is simply dropped, loading entry and all,
 * because the reset already removed it.
 *
 * @param {object} options
 * @param {() => {from: string, to: string}} options.period The window to ask for.
 * @param {(nmId: number, params: object) => Promise<object>} options.fetch
 */
import { ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'

export function useSkuSizes({ period, fetch }) {
  const sizes = ref({})
  let generation = 0

  function put(nmId, entry) {
    sizes.value = { ...sizes.value, [nmId]: entry }
  }

  /** Forget every article's sizes — the window they belong to is being replaced. */
  function reset() {
    generation += 1
    sizes.value = {}
  }

  /** Load one article's sizes for the current window, unless already loaded or loading. */
  async function load(nmId) {
    const current = sizes.value[nmId]
    if (current && (current.loading || current.data)) return
    const { from, to } = period()
    if (!from || !to) return
    const mine = generation
    put(nmId, { loading: true, error: '', data: null })
    try {
      const data = await fetch(nmId, { date_from: from, date_to: to })
      if (mine === generation) put(nmId, { loading: false, error: '', data })
    } catch (error) {
      if (mine === generation) {
        put(nmId, { loading: false, error: extractErrorMessage(error), data: null })
      }
    }
  }

  return { sizes, load, reset }
}
