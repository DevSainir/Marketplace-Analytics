/**
 * DORMANT — «Рекламные кластеры» is deliberately not rendered anywhere in the
 * app (hidden 2026-09-09; see the note in `MonitoringView.vue`). This is NOT
 * dead code and must survive a cleanup pass: the feature is finished and kept
 * warm behind an off switch, the backend keeps ingesting the data, and turning
 * it back on is a template change with no work here.
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
 * @returns {ReturnType<typeof useClusterSearchStore>} The store the block reads.
 */
export function useSkuClusters() {
  const monitoring = useMonitoringStore()
  const clusters = useClusterSearchStore()

  watch(
    // A plain string, so the watcher fires once per real change instead of on
    // every re-render of the detail object.
    () => {
      const product = monitoring.currentProduct
      if (!product) return ''
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
