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
import { computed, ref, watch } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { isoDaysAgo } from '@/core/utils/dates'
import * as api from '@/modules/heatmap/api'
import { useMembersStore } from '@/modules/profile'

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

/** The bucket of articles in none of the groups — the heatmap's own words. */
export const UNGROUPED = 'Без группы'

/** The bucket of articles WB left without a subject or a brand. */
export const UNNAMED = '(не указан)'

/**
 * Split items by subject, brand or group — the cuts `GroupingChips` offers
 * beyond «Артикулы», which is no split at all.
 *
 * By group an item lands in EVERY group it is in, and the rest share one
 * «Без группы» bucket: the heatmap's rule. The buckets can then hold more
 * items between them than there are, so a page's «Итого» is summed over the
 * items, never over the buckets.
 *
 * @template T
 * @param {T[]} items
 * @param {'subject'|'brand'|'group'} cut
 * @param {{nmId: (item: T) => number, subject: (item: T) => string,
 *   brand: (item: T) => string, groups: Array<{id: string, name: string, nm_ids: number[]}>}} how
 * @returns {Array<{key: string, label: string, items: T[]}>} In first-seen
 *   order for a subject or a brand, in the groups' order for a group.
 */
export function splitBy(items, cut, how) {
  if (cut === 'group') {
    const placed = new Set()
    const buckets = []
    for (const group of how.groups) {
      const members = new Set(group.nm_ids)
      const inside = items.filter((item) => members.has(how.nmId(item)))
      if (!inside.length) continue
      inside.forEach((item) => placed.add(item))
      buckets.push({ key: `group:${group.id}`, label: group.name, items: inside })
    }
    const rest = items.filter((item) => !placed.has(item))
    if (rest.length) buckets.push({ key: 'group:none', label: UNGROUPED, items: rest })
    return buckets
  }
  const byName = new Map()
  for (const item of items) {
    const name = how[cut](item) || UNNAMED
    if (!byName.has(name)) byName.set(name, [])
    byName.get(name).push(item)
  }
  return [...byName].map(([name, inside]) => ({
    key: `${cut}:${name}`,
    label: name,
    items: inside,
  }))
}

/**
 * The pages that carry the group filter — the backend's `GROUP_MODULES`.
 * Groups are a control on these pages, not a page of their own, so holding any
 * one of them is what lets a caller read the groups (`require_groups`).
 */
export const GROUP_MODULES = ['summary', 'finreports', 'heatmap', 'advertising']

/** Whether the caller may read the groups at all — see `GROUP_MODULES`. */
export function useGroupsReadable() {
  const members = useMembersStore()
  return computed(() => GROUP_MODULES.some((key) => members.canReach(key)))
}

/**
 * What a page cutting by «Группы» needs: the list, loaded when the cut is
 * chosen, and whether the caller may have it at all. A caller who may not is
 * put back on «Артикулы» rather than shown a cut that can only say «Без группы».
 * Every page with the cut is one of `GROUP_MODULES`, so that is a safety net
 * for a page added later outside the list, not a case that happens today.
 *
 * @param {import('vue').Ref<string>} cut The page's cut.
 */
export function useGroupCut(cut) {
  const store = useGroupsStore()
  const readable = useGroupsReadable()
  watch(
    [cut, readable],
    ([value, ok]) => {
      if (value !== 'group') return
      if (!ok) cut.value = 'sku'
      else store.load().catch(() => {})
    },
    { immediate: true },
  )
  return { groups: computed(() => store.groups), readable }
}
