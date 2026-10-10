/**
 * The matrix header's campaign links: which WB campaign each traffic group ran
 * on a given day, the link to it, and the hover card that shows its id.
 *
 * The id comes off the backend's working copy — every advertising bucket in
 * `matrix_base` names the campaign that delivered it (`campaign_id`) — and a
 * group spans several buckets (its zones), so a group's campaign is whichever
 * of its buckets names one.
 *
 * The hover card is not decoration. The link is built from WB's own URL shape
 * (`wbLinks.js`), which WB can change without notice; the id in the card is
 * selectable and copyable, so the campaign can still be found by hand in the
 * cabinet if the link ever stops landing.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { visibleArea } from '@/core/utils/tipFit'
import { campaignUrl } from '@/modules/labs/wbLinks'

/** The backend buckets each campaign group of TRAFFIC_GROUPS delivers into. */
export const GROUP_BUCKETS = {
  uni: ['uni_search', 'uni_shelves'],
  manual_search: ['manual_search', 'manual_catalog'],
  manual_shelves: ['manual_shelves'],
  cpc: ['cpc_search', 'cpc_shelves'],
}

/**
 * Per ISO day, the campaign id behind each group that ran one.
 *
 * @param {{days?: Array<{day: string, buckets: Record<string, {campaign_id?: number|null}>}>}|null} matrixBase
 * @returns {Record<string, Record<string, number>>}
 */
export function campaignIdsByDay(matrixBase) {
  const byDay = {}
  for (const { day, buckets } of matrixBase?.days ?? []) {
    for (const [group, keys] of Object.entries(GROUP_BUCKETS)) {
      const id = keys.map((key) => buckets?.[key]?.campaign_id).find(Boolean)
      if (id) (byDay[day] ??= {})[group] = id
    }
  }
  return byDay
}

/** How long the card waits before closing, so the pointer can cross onto it. */
const CLOSE_DELAY_MS = 250

/**
 * @param {() => {nmId?: number|null, byDay?: object}} campaigns reactive source
 * @param {() => Array<{iso: string}>} days the table's window, oldest first
 */
export function useCampaignLinks(campaigns, days) {
  /** The group's campaign on that day, with its link, or null. */
  function advertFor(iso, groupKey) {
    const id = campaigns()?.byDay?.[iso]?.[groupKey]
    if (!id) return null
    const window = days()
    return {
      id,
      href: campaignUrl(id, {
        nmId: campaigns()?.nmId,
        from: window[0]?.iso,
        to: window.at(-1)?.iso,
      }),
    }
  }

  const tip = ref(null) // { id: number, x: number, y: number } | null
  let closeTimer = null

  function keepTip() {
    clearTimeout(closeTimer)
  }

  function showTip(event, id) {
    keepTip()
    const rect = event.currentTarget.getBoundingClientRect()
    tip.value = { id, x: rect.left, y: rect.bottom + 4, area: visibleArea(event.currentTarget) }
  }

  function hideTip() {
    keepTip()
    closeTimer = setTimeout(() => {
      tip.value = null
    }, CLOSE_DELAY_MS)
  }

  // `fixed` and teleported, so it must close on any scroll or it strands
  // itself over whatever slides under it.
  function closeNow() {
    keepTip()
    tip.value = null
  }
  onMounted(() => document.addEventListener('scroll', closeNow, true))
  onBeforeUnmount(() => {
    document.removeEventListener('scroll', closeNow, true)
    keepTip()
  })

  return { advertFor, tip, showTip, hideTip, keepTip }
}
