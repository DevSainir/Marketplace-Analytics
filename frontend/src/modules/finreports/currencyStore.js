/**
 * The active кабинет's settlement currency — the unit of every money figure.
 *
 * A store of its own rather than a field on each response: monitoring and the
 * A/Б tests print money too, and the backend cannot put the unit on their
 * responses without monitoring depending on finreports, which already depends
 * on monitoring. So it is one small request per session, shared by every page.
 * Switching кабинет reloads the app (`App.vue`, the profile page), so the
 * answer cannot go stale underneath a page.
 *
 * `ensureLoaded()` never rejects. A failed or not-yet-answered request leaves
 * `currency` empty, every label prints bare numbers instead of a guessed unit,
 * and the next page that asks tries again.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { fetchSettlementCurrency } from '@/modules/finreports/api'

export const useCurrencyStore = defineStore('currency', () => {
  /** ISO code (`KGS`); `''` while unknown. */
  const currency = ref('')

  let loadPromise = null

  /** Fetch the currency once; concurrent callers share the request. */
  function ensureLoaded() {
    loadPromise ??= fetchSettlementCurrency()
      .then((code) => {
        currency.value = code ?? ''
      })
      .catch(() => {
        loadPromise = null
      })
    return loadPromise
  }

  return { currency, ensureLoaded }
})
