/**
 * «Реклама» Pinia store (setup style).
 *
 * The window is the only thing that costs a round trip. The bonus switch, the
 * table's grain, its filters and its search are all answered from the payload.
 *
 * The bonus switch is remembered per browser. WB's bonus pool funds advertising
 * in waves — on «Демо» 33 % of September's spend, up to 85 % of a day, and
 * nothing at all since 26.09.2026 — so a reader who does not track it wants it
 * gone for good, and one who does wants it to stay on.
 */
import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { presetRange } from '@/core/utils/calendarModel'
import { fetchAdvertising, fetchAdvertisingSpan } from '@/modules/advertising/api'
import { bidCards } from '@/modules/advertising/zoneModel'

/** Default window: thirty days, the span an advertising budget is reviewed over. */
const DEFAULT_DAYS = 30

const BONUS_KEY = 'advertising.showBonus'

/** The remembered switch; private windows and blocked storage fall back to «on». */
function readBonusSwitch() {
  try {
    return localStorage.getItem(BONUS_KEY) !== 'off'
  } catch {
    return true
  }
}

/** YYYY-MM-DD in the local calendar. */
function isoDate(date) {
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  return shifted.toISOString().slice(0, 10)
}

export const useAdvertisingStore = defineStore('advertising', () => {
  const initial = presetRange(DEFAULT_DAYS, isoDate(new Date()))
  const dateFrom = ref(initial.from)
  const dateTo = ref(initial.to)

  const span = ref(null)
  const data = ref(null)
  const loading = ref(false)
  const error = ref('')
  let inFlight = null

  const showBonus = ref(readBonusSwitch())
  const group = ref('sku')
  const filters = reactive({ query: '', subject: '', brand: '' })

  const currency = computed(() => data.value?.currency ?? '')
  const totals = computed(() => data.value?.totals ?? null)
  /** Whether the window carries any WB-funded spend at all. */
  const hasBonus = computed(() => Number(totals.value?.bonus ?? 0) > 0)
  /** What every bonus element on the page obeys: the switch, and the data. */
  const bonusVisible = computed(() => showBonus.value && hasBonus.value)
  /**
   * ДРР divides ad spend by settled sales. When the spend was billed in a
   * currency other than the settlement's, that is two units — withheld.
   */
  const drrComparable = computed(() =>
    (data.value?.ad_currencies ?? []).every((code) => code === currency.value),
  )
  /** The «Куда ушли деньги» cards, and the spend no card can hold. */
  const bids = computed(() => bidCards(data.value?.zones ?? []))

  async function load() {
    inFlight?.abort()
    const controller = new AbortController()
    inFlight = controller
    loading.value = true
    error.value = ''
    try {
      data.value = await fetchAdvertising(
        { date_from: dateFrom.value, date_to: dateTo.value },
        controller.signal,
      )
    } catch (cause) {
      if (controller.signal.aborted) return
      error.value = extractErrorMessage(cause)
      data.value = null
    } finally {
      if (inFlight === controller) {
        inFlight = null
        loading.value = false
      }
    }
  }

  /**
   * Open on the last thirty days, and learn the advertising span ALONGSIDE.
   *
   * The two used to run one after the other — the span first, so the window
   * could end on its last day — which put a whole round trip in front of the
   * first figure. Advertising statistics are a stream that reaches today, so
   * the window can end today without waiting to be told; the span arrives in
   * parallel and only feeds the picker («Вся история» starts at its first
   * day). A failed span read is swallowed: the page does not need it to load.
   */
  async function init() {
    const spanRead = fetchAdvertisingSpan()
      .then((value) => {
        span.value = value
      })
      .catch(() => {
        span.value = null
      })
    await Promise.all([spanRead, load()])
  }

  function setPeriod(from, to) {
    if (from === dateFrom.value && to === dateTo.value) return
    dateFrom.value = from
    dateTo.value = to
    return load()
  }

  function setShowBonus(on) {
    showBonus.value = on
    try {
      localStorage.setItem(BONUS_KEY, on ? 'on' : 'off')
    } catch {
      // A private window: the switch still works, it just is not remembered.
    }
  }

  function clearFilters() {
    filters.query = ''
    filters.subject = ''
    filters.brand = ''
  }

  return {
    dateFrom,
    dateTo,
    span,
    data,
    loading,
    error,
    showBonus,
    group,
    filters,
    currency,
    totals,
    hasBonus,
    bonusVisible,
    drrComparable,
    bids,
    init,
    load,
    setPeriod,
    setShowBonus,
    clearFilters,
  }
})
