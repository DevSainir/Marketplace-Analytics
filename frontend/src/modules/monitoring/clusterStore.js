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
import {
  fetchPinnedKeywords,
  fetchSkuClusters,
  getRefreshStatus,
  pinKeyword,
  probeSkuSearchPosition,
  refreshAllPositions,
  unpinKeyword,
} from '@/modules/monitoring/api'

/** How often the «Проверить все позиции» run is polled, in ms. The task probes
 *  one phrase a minute, so a tighter poll would only add requests. */
const POSITION_POLL_MS = 5000

/**
 * Russian plural for «запрос» — 1 запрос, 2 запроса, 5 запросов.
 *
 * @param {number} count How many phrases the run will probe.
 * @returns {string} The noun in the form that count requires.
 */
function pluralPhrases(count) {
  const mod100 = count % 100
  if (mod100 >= 11 && mod100 <= 14) return 'запросов'
  const mod10 = count % 10
  if (mod10 === 1) return 'запрос'
  if (mod10 >= 2 && mod10 <= 4) return 'запроса'
  return 'запросов'
}

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

  /** Pinned phrases and their last recorded positions (cards under the search row). */
  const pins = ref([])
  const pinsLoading = ref(false)
  /** True once a pins load finished for the current SKU (empty-state guard). */
  const pinsLoaded = ref(false)
  const pinsError = ref('')
  /** True while a «Проверить все позиции» run is queued or running. */
  const refreshingAll = ref(false)
  /** What that run reported, so the row can say «Проверяем 12 запросов…». */
  const refreshMessage = ref('')

  /** In-flight request guards: a newer SKU/window/search always wins. */
  let clustersAbort = null
  let positionAbort = null
  let pinsAbort = null
  let pollTimer = null

  const hasClusters = computed(() => clusters.value.length > 0)
  const hasPins = computed(() => pins.value.length > 0)

  /**
   * The props «Позиции в поиске» renders from, as one object.
   *
   * Bundled here rather than spelled out in the view because this store already
   * owns every field: the view stays composition (`v-bind` + the handlers), and
   * the panel keeps declaring its own props, so it is still a dumb component.
   */
  const positionPanelProps = computed(() => ({
    position: position.value,
    positionLoading: positionLoading.value,
    positionError: positionError.value,
    pins: pins.value,
    pinsError: pinsError.value,
    pinsLoaded: pinsLoaded.value,
    refreshingAll: refreshingAll.value,
    refreshMessage: refreshMessage.value,
  }))

  /** The props «Рекламные кластеры» renders from (same reasoning as above). */
  const clusterTableProps = computed(() => ({
    clusters: clusters.value,
    clustersLoading: clustersLoading.value,
    clustersError: clustersError.value,
    loaded: loaded.value,
  }))

  /** Drop everything (the page lost its SKU). */
  function reset() {
    clustersAbort?.abort()
    positionAbort?.abort()
    pinsAbort?.abort()
    stopPolling()
    nmId.value = null
    clusters.value = []
    clustersError.value = ''
    loaded.value = false
    query.value = ''
    position.value = null
    positionError.value = ''
    pins.value = []
    pinsError.value = ''
    pinsLoaded.value = false
    refreshingAll.value = false
    refreshMessage.value = ''
  }

  /** Stop watching a queued run — on reset, on completion, on navigation away. */
  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
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
    const skuChanged = nmId.value !== id
    if (skuChanged) {
      position.value = null
      positionError.value = ''
      pins.value = []
      pinsError.value = ''
      pinsLoaded.value = false
    }
    nmId.value = id
    // Pins belong to the SKU, not to the window, so they are fetched only when
    // the SKU actually changed — and NOT awaited: they are a separate, cheap
    // request and must not hold the cluster table behind them.
    if (skuChanged) void loadPins(id)
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

  /**
   * Load the SKU's pinned phrases and their stored positions.
   *
   * Never throws and never blocks the rest of the block: pins are a convenience
   * on top of the panel, so a failure here shows one line and leaves the cluster
   * table and the search box working.
   *
   * @param {number} id WB SKU identifier.
   */
  async function loadPins(id) {
    pinsAbort?.abort()
    pinsAbort = new AbortController()
    pinsLoading.value = true
    pinsError.value = ''
    try {
      const data = await fetchPinnedKeywords(id, pinsAbort.signal)
      // A late response for the SKU we already left would repaint the new SKU's
      // cards with the old one's phrases.
      if (nmId.value !== id) return
      pins.value = data.items ?? []
      pinsLoaded.value = true
    } catch (err) {
      if (err.code === 'ERR_CANCELED') return
      pins.value = []
      pinsError.value = extractErrorMessage(err)
      pinsLoaded.value = true
    } finally {
      pinsLoading.value = false
    }
  }

  /**
   * Pin a phrase to the current SKU («Закрепить»).
   *
   * The card appears immediately with no number: pinning deliberately does not
   * probe, so it stays instant. The next scheduled run or «Проверить все
   * позиции» fills the position in.
   *
   * @param {string} phrase The phrase to pin.
   */
  async function pin(phrase) {
    const term = phrase.trim()
    if (!term || !nmId.value) return
    pinsError.value = ''
    try {
      await pinKeyword(nmId.value, term)
      await loadPins(nmId.value)
    } catch (err) {
      pinsError.value = extractErrorMessage(err)
    }
  }

  /**
   * Unpin a phrase from the current SKU.
   *
   * @param {string} phrase The pinned phrase.
   */
  async function unpin(phrase) {
    if (!nmId.value) return
    pinsError.value = ''
    try {
      await unpinKeyword(nmId.value, phrase)
      pins.value = pins.value.filter((item) => item.keyword !== phrase)
    } catch (err) {
      pinsError.value = extractErrorMessage(err)
    }
  }

  /**
   * «Проверить все позиции» — queue a re-probe of every pinned phrase.
   *
   * The task probes phrases about a minute apart, so this returns as soon as the
   * work is queued and then polls until it finishes, reloading the cards once.
   * The button stays disabled meanwhile: a second run would only be refused by
   * the backend's lock, and the seller would have no idea why.
   */
  async function refreshAllPinned() {
    if (!nmId.value || refreshingAll.value) return
    refreshingAll.value = true
    pinsError.value = ''
    refreshMessage.value = ''
    try {
      const { task_id: taskId, pinned_count: pinnedCount } = await refreshAllPositions()
      if (!pinnedCount) {
        refreshMessage.value = 'Нет закреплённых запросов — закрепите фразу, чтобы отслеживать её.'
        refreshingAll.value = false
        return
      }
      // States the SCOPE, because the run covers every SKU in the workspace
      // while the cards below show only this one's: without saying so, a run
      // that refreshed another SKU's phrases looks like a button that did
      // nothing.
      refreshMessage.value =
        `Проверяем ${pinnedCount} ${pluralPhrases(pinnedCount)} по всем артикулам воркспейса. ` +
        'Около минуты на запрос.'
      pollRun(taskId)
    } catch (err) {
      refreshingAll.value = false
      pinsError.value = extractErrorMessage(err)
    }
  }

  /**
   * Turn a finished run into one sentence a seller can act on.
   *
   * The task reports SUCCESS even when WB refused every phrase — a throttled
   * probe is caught per phrase so one refusal cannot cost the run the others —
   * so `successful` alone said «Позиции обновлены.» over an unchanged timestamp.
   * Prod, 2026-08-17: one pinned phrase, two 429s, `pins_updated: 0`, and the UI
   * claimed success. `failed_sources` carries the phrases WB withheld.
   *
   * @param {{successful: boolean, failed_sources?: string[]}} status Finished status.
   * @returns {string} The message to show.
   */
  function describeRun(status) {
    if (!status.successful) {
      return 'Проверка не завершилась. Позиции остались с прошлой проверки.'
    }
    const withheld = status.failed_sources ?? []
    if (withheld.length) {
      // Naming the phrases matters: with several pinned, "some failed" leaves the
      // seller comparing timestamps by hand to find which number is stale.
      const quoted = withheld.map((phrase) => `«${phrase}»`).join(', ')
      return (
        `WB ограничил частоту запросов — не удалось проверить: ${quoted}. ` +
        'Прежние позиции сохранены; повторите через минуту или дождитесь следующей проверки.'
      )
    }
    if (!pins.value.length) {
      return 'Проверка закончена. У этого артикула нет закреплённых запросов — обновились фразы других артикулов.'
    }
    return 'Позиции обновлены.'
  }

  /**
   * Watch a queued run until it finishes, then reload the cards.
   *
   * A poll failure ends the watch rather than retrying forever: the run itself
   * is unaffected, and its results land on the next page load either way.
   *
   * @param {string} taskId The enqueued task.
   */
  function pollRun(taskId) {
    stopPolling()
    pollTimer = setTimeout(async () => {
      try {
        const status = await getRefreshStatus(taskId)
        if (!status.ready) {
          pollRun(taskId)
          return
        }
        refreshingAll.value = false
        if (nmId.value) await loadPins(nmId.value)
        // Says something on success too: a run whose phrases all belong to other
        // SKUs changes nothing on this page, and silence there is exactly what
        // reads as «ничего не произошло».
        refreshMessage.value = describeRun(status)
      } catch {
        refreshingAll.value = false
        refreshMessage.value = ''
      }
    }, POSITION_POLL_MS)
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
    pins,
    pinsLoading,
    pinsError,
    pinsLoaded,
    hasPins,
    refreshingAll,
    refreshMessage,
    positionPanelProps,
    clusterTableProps,
    reset,
    loadForSku,
    checkPosition,
    loadPins,
    pin,
    unpin,
    refreshAllPinned,
  }
})
