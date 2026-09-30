/**
 * The heatmap's hand-set norms («Норма: ручной ввод»), one per article and metric.
 *
 * Its own store because nothing about a norm costs the grid a request: the
 * norms are read once, all of them, and a change repaints what is already on
 * screen. A save is optimistic — the cell recolours as the field is left — and
 * put back if the backend refuses it (a read-only manager, a card that left
 * the кабинет).
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import * as api from '@/modules/heatmap/api'

const keyOf = (nmId, metric) => `${nmId}:${metric}`

export const useHeatmapNormsStore = defineStore('heatmapNorms', () => {
  /** `'default'` paints against the median, `'manual'` against the norms below. */
  const mode = ref('default')
  const values = ref({})
  const error = ref('')

  async function load() {
    const { items } = await api.fetchNorms()
    values.value = Object.fromEntries(items.map((n) => [keyOf(n.nm_id, n.metric), n.value]))
  }

  /** @returns {number|null} */
  function normOf(nmId, metric) {
    return values.value[keyOf(nmId, metric)] ?? null
  }

  /**
   * Set or (with `null`) clear an article's norm on a metric.
   *
   * @param {number} nmId
   * @param {string} metric
   * @param {number|null} value
   */
  async function save(nmId, metric, value) {
    const key = keyOf(nmId, metric)
    const before = values.value[key] ?? null
    if (before === value) return
    values.value = { ...values.value, [key]: value }
    if (value === null) delete values.value[key]
    error.value = ''
    try {
      if (value === null) await api.deleteNorm(nmId, metric)
      else await api.saveNorm(nmId, metric, value)
    } catch (err) {
      values.value = { ...values.value, [key]: before }
      if (before === null) delete values.value[key]
      error.value = extractErrorMessage(err)
    }
  }

  return { mode, values, error, load, normOf, save }
})
