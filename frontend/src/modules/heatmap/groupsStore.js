/**
 * «Группы» — a кабинет's hand-made sets of articles, one list for every page.
 *
 * The heatmap had them alone; the P&L, the balance and advertising filter by
 * them too now. One store, so a group created or edited on one page is the
 * group every other page shows — the list lives on the server and is the same
 * for everyone in the кабинет, and this is its one copy in the tab.
 *
 * `revision` ticks on every change made here (not on a plain reload), so a page
 * whose figures depend on the groups — the heatmap cut by them — knows to ask
 * again without asking on every visit.
 *
 * A кабинет switch reloads the whole app, so nothing here is keyed by кабинет.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { isoDaysAgo } from '@/core/utils/dates'
import * as api from '@/modules/heatmap/api'

/** The window the group editor ranks articles by when the page has none of its own. */
const CARDS_DAYS = 30

export const useGroupsStore = defineStore('heatmap-groups', () => {
  const groups = ref([])
  const revision = ref(0)
  const busy = ref(false)
  const error = ref('')
  /** Every card of the кабинет, most-ordered first — what the editor picks from. */
  const cards = ref([])

  /** Refreshed on every page that shows them: someone else may have changed one. */
  async function load() {
    groups.value = (await api.fetchGroups()).items
  }

  async function loadCards() {
    if (cards.value.length) return
    const { items } = await api.fetchCatalog({
      date_from: isoDaysAgo(CARDS_DAYS),
      date_to: isoDaysAgo(1),
    })
    cards.value = items
  }

  /**
   * Run one change, then reload the list.
   *
   * @returns {Promise<boolean>} Whether it went through.
   */
  async function change(action) {
    busy.value = true
    error.value = ''
    try {
      await action()
      await load()
      revision.value += 1
      return true
    } catch (err) {
      error.value = extractErrorMessage(err)
      return false
    } finally {
      busy.value = false
    }
  }

  /** @param {{id?: string, name: string, nm_ids: number[]}} group */
  function save(group) {
    const payload = { name: group.name, nm_ids: group.nm_ids }
    return change(() => (group.id ? api.updateGroup(group.id, payload) : api.createGroup(payload)))
  }

  function remove(id) {
    return change(() => api.deleteGroup(id))
  }

  return { groups, revision, busy, error, cards, load, loadCards, save, remove }
})

/**
 * The articles of the chosen groups, or `null` when none is chosen — no
 * filter, not an empty one. A group deleted since it was chosen counts for
 * nothing rather than for everything.
 *
 * @param {Array<{id: string, nm_ids: number[]}>} groups
 * @param {string[]} ids
 * @returns {Set<number>|null}
 */
export function articlesOfGroups(groups, ids) {
  if (!ids.length) return null
  const chosen = new Set(ids)
  return new Set(groups.filter((group) => chosen.has(group.id)).flatMap((group) => group.nm_ids))
}
