/**
 * «Рекламные кластеры» is shown per workspace: hidden for everyone on 2026-09-09,
 * back since 2026-09-26 for the workspaces whose `search_clusters_enabled` is
 * set. Where it is off this composable fetches nothing — see the note in
 * `MonitoringView.vue`.
 *
 * Keeps the SKU page's cluster block in step with the SKU and window on screen.
 *
 * Extracted from `MonitoringView` for the same reason `useSearchQuerySync` was:
 * the view composes, it does not orchestrate. The rule here is that the block
 * follows the LOADED detail — `currentProduct.window`, not the period selector's
 * draft — so the clusters always describe the same window as the table above
 * them, including after Back/forward, and never fire on a period the user is
 * still editing.
 */
import { watch } from 'vue'

import { useClusterSearchStore } from '@/modules/monitoring/clusterStore'
import { useMonitoringStore } from '@/modules/monitoring/store'

/**
 * @param {() => boolean} enabled Whether the current workspace shows the block;
 *   read reactively, so a workspace list that loads late still switches it on.
 * @returns {ReturnType<typeof useClusterSearchStore>} The store the block reads.
 */
export function useSkuClusters(enabled) {
  const monitoring = useMonitoringStore()
  const clusters = useClusterSearchStore()

  watch(
    // A plain string, so the watcher fires once per real change instead of on
    // every re-render of the detail object.
    () => {
      const product = monitoring.currentProduct
      if (!product || !enabled()) return ''
      return [product.nm_id, product.window?.start ?? '', product.window?.end ?? ''].join('|')
    },
    (key) => {
      if (!key) {
        clusters.reset()
        return
      }
      const [nmId, from, to] = key.split('|')
      clusters.loadForSku(Number(nmId), { from, to })
    },
    { immediate: true },
  )

  return clusters
}
