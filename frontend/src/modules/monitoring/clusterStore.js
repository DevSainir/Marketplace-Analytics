/**
 * «Поиск по кластерам» Pinia store — the block at the bottom of a SKU's page.
 *
 * A store of its own rather than part of the monitoring one, because its two
 * halves have different costs and different failure modes and neither may take
 * the SKU page down with it:
 *
 * - `clusters` — the SKU's own advertising per search cluster, from harvested
 *   history. Loads with the SKU and its window, always shown.
 * - `position` — where the SKU ranks in WB's public search RIGHT NOW, and only
 *   for a phrase someone typed. Slow, rate-limited by WB, allowed to fail on its
 *   own: `positionError` is surfaced under the search bar while everything else
 *   keeps its data.
 *
 * The two are never merged. One is a window of paid impressions, the other a
 * sample taken seconds ago from a personalized, regional result page.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { fetchSkuClusters, probeSkuSearchPosition } from '@/modules/monitoring/api'

export const useClusterSearchStore = defineStore('monitoringClusters', () => {
  /** The SKU the loaded block belongs to (guards against a late response). */
  const nmId = ref(null)
  const clusters = ref([])
  const clustersLoading = ref(false)
  const clustersError = ref('')
  /** True once a load finished, so «нет данных» never flashes before the first. */
  const loaded = ref(false)

  const query = ref('')
  const position = ref(null)
  const positionLoading = ref(false)
  const positionError = ref('')

  /** In-flight request guards: a newer SKU/window/search always wins. */
  let clustersAbort = null
  let positionAbort = null

  const hasClusters = computed(() => clusters.value.length > 0)

  /** Drop everything (the page lost its SKU). */
  function reset() {
    clustersAbort?.abort()
    positionAbort?.abort()
    nmId.value = null
    clusters.value = []
    clustersError.value = ''
    loaded.value = false
    query.value = ''
    position.value = null
    positionError.value = ''
  }

  /**
   * Load the SKU's clusters for the page's window.
   *
   * @param {number} id WB SKU identifier.
   * @param {{from?: string, to?: string}} [window] The page's analysis window.
   */
  async function loadForSku(id, { from = '', to = '' } = {}) {
    clustersAbort?.abort()
    clustersAbort = new AbortController()
    // A different SKU invalidates the typed phrase's answer: the rank belonged
    // to the previous card, and showing it under the new one would be a lie.
    if (nmId.value !== id) {
      position.value = null
      positionError.value = ''
    }
    nmId.value = id
    clustersLoading.value = true
    clustersError.value = ''
    try {
      const data = await fetchSkuClusters(
        id,
        { date_from: from || undefined, date_to: to || undefined },
        clustersAbort.signal,
      )
      clusters.value = data.items ?? []
      loaded.value = true
    } catch (err) {
      if (err.code === 'ERR_CANCELED') return
      clusters.value = []
      clustersError.value = extractErrorMessage(err)
      loaded.value = true
    } finally {
      clustersLoading.value = false
    }
  }

  /**
   * Check where the current SKU ranks in WB search for a phrase.
   *
   * Never throws: a throttled WB (HTTP 502 from our backend) leaves the cluster
   * table intact and shows the reason — the panel must not be able to report
   * «нет в выдаче» for a check that never happened.
   *
   * @param {string} phrase The phrase to check.
   * @param {{refresh?: boolean}} [options] `refresh` bypasses the backend cache.
   */
  async function checkPosition(phrase, { refresh = false } = {}) {
    const term = phrase.trim()
    if (!term || !nmId.value) return
    positionAbort?.abort()
    positionAbort = new AbortController()
    query.value = term
    positionLoading.value = true
    positionError.value = ''
    try {
      position.value = await probeSkuSearchPosition(
        nmId.value,
        term,
        { refresh },
        positionAbort.signal,
      )
    } catch (err) {
      if (err.code === 'ERR_CANCELED') return
      position.value = null
      positionError.value = extractErrorMessage(err)
    } finally {
      positionLoading.value = false
    }
  }

  return {
    nmId,
    clusters,
    clustersLoading,
    clustersError,
    loaded,
    hasClusters,
    query,
    position,
    positionLoading,
    positionError,
    reset,
    loadForSku,
    checkPosition,
  }
})
