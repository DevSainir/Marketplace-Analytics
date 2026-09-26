/**
 * Rendered only for кабинеты whose `search_clusters_enabled` is set — NEVA since
 * 2026-09-26; hidden for everyone else since 2026-09-09. See the note in
 * `MonitoringView.vue`.
 *
 * «Поиск по кластерам» Pinia store — the block at the bottom of a SKU's page.
 *
 * A store of its own rather than part of the monitoring one: the block loads on
 * its own schedule (the SKU and the page's window), and a cluster request that
 * fails must leave the rest of the SKU page standing — `clustersError` is
 * surfaced inside the block while everything else keeps its data.
 *
 * What it holds is a window of PAID impressions per search cluster, harvested
 * from WB's advertising statistics. It is never an organic rank. The live
 * position probe that used to be this store's second half was removed on
 * 2026-08-27 — `docs/monitoring/LIVE_POSITION.md` records why.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { fetchSkuClusters } from '@/modules/monitoring/api'

export const useClusterSearchStore = defineStore('monitoringClusters', () => {
  /** The SKU the loaded block belongs to (guards against a late response). */
  const nmId = ref(null)
  const clusters = ref([])
  const clustersLoading = ref(false)
  const clustersError = ref('')
  /** True once a load finished, so «нет данных» never flashes before the first. */
  const loaded = ref(false)

  /** In-flight request guard: a newer SKU/window always wins. */
  let clustersAbort = null

  const hasClusters = computed(() => clusters.value.length > 0)

  /**
   * The props «Рекламные кластеры» renders from, as one object.
   *
   * Bundled here rather than spelled out in the view because this store already
   * owns every field: the view stays composition (`v-bind`), and the table keeps
   * declaring its own props, so it is still a dumb component.
   */
  const clusterTableProps = computed(() => ({
    clusters: clusters.value,
    clustersLoading: clustersLoading.value,
    clustersError: clustersError.value,
    loaded: loaded.value,
  }))

  /** Drop everything (the page lost its SKU). */
  function reset() {
    clustersAbort?.abort()
    nmId.value = null
    clusters.value = []
    clustersError.value = ''
    loaded.value = false
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

  return {
    nmId,
    clusters,
    clustersLoading,
    clustersError,
    loaded,
    hasClusters,
    clusterTableProps,
    reset,
    loadForSku,
  }
})
