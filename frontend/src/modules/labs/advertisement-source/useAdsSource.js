/**
 * The lab's state: the loaded datapack, the window, the price base and the
 * table's cut, plus every figure the block derives from them.
 *
 * A composable rather than a Pinia store on purpose: the lab is one route, its
 * state dies with it, and nothing else reads it. When the block moves into the
 * product the derivations stay (they are `adsSpend.js` / `adsSkuRows.js`) and
 * this becomes the store that feeds them from an endpoint.
 *
 * The datapack is a `shallowRef`: it is a megabyte of packed arrays nobody
 * mutates, and deep reactivity would have Vue proxy every row of it.
 */
import { computed, reactive, ref, shallowRef } from 'vue'

import { fetchAdsDatapack } from '@/modules/labs/advertisement-source/api'
import {
  AD_GROUPS,
  cabinetDrr,
  filterOptions,
  groupRows,
  pickRows,
  skuAdRows,
  sliceBySku,
  sumRows,
} from '@/modules/labs/advertisement-source/adsSkuRows'
import {
  dailySpend,
  kindRows,
  reconciliation,
  spendWindow,
  zoneBars,
  zoneShares,
} from '@/modules/labs/advertisement-source/adsSpend'

export function useAdsSource() {
  const pack = shallowRef(null)
  const loading = ref(true)
  const error = ref('')

  const from = ref('')
  const to = ref('')
  /** `gross` — WB's realisation price; `card` — the card price before СПП. */
  const revBase = ref('gross')
  const group = ref('sku')
  const filters = reactive({ query: '', subject: '', brand: '' })

  async function load() {
    loading.value = true
    error.value = ''
    try {
      pack.value = await fetchAdsDatapack()
      // The P&L window, not the spend file's: per-SKU money only exists there,
      // and a wider default would show spend with no revenue to weigh it by.
      from.value = pack.value.meta.pnl_from
      to.value = pack.value.meta.pnl_to
    } catch (failure) {
      error.value = failure.message
    } finally {
      loading.value = false
    }
  }

  const ads = computed(() => pack.value?.ads ?? null)
  const currency = computed(() => pack.value?.meta.currency ?? '')
  /** The last settled day — where the period presets end. */
  const lastDay = computed(() => pack.value?.meta.pnl_to ?? '')

  const spend = computed(() => spendWindow(ads.value, from.value, to.value))
  const zones = computed(() => zoneShares(ads.value, from.value, to.value))
  const kinds = computed(() => kindRows(spend.value, zones.value))
  const bars = computed(() => zoneBars(spend.value, zones.value))
  const daily = computed(() => dailySpend(ads.value, from.value, to.value))
  const notes = computed(() => reconciliation(ads.value))

  const slice = computed(() => sliceBySku(pack.value, from.value, to.value))
  const drr = computed(() => cabinetDrr(pack.value, slice.value, revBase.value))
  const skuRows = computed(() => skuAdRows(pack.value, slice.value, revBase.value))
  const options = computed(() => filterOptions(skuRows.value))
  const picked = computed(() => pickRows(skuRows.value, filters))
  const rows = computed(() => groupRows(picked.value, group.value))
  const totals = computed(() => sumRows(rows.value))
  const groupDef = computed(() => AD_GROUPS.find((g) => g.id === group.value))

  const isFiltering = computed(() => Boolean(filters.query || filters.subject || filters.brand))

  function setPeriod(range) {
    from.value = range.from
    to.value = range.to
  }

  function clearFilters() {
    filters.query = ''
    filters.subject = ''
    filters.brand = ''
  }

  return {
    load,
    loading,
    error,
    available: computed(() => Boolean(ads.value?.available)),
    from,
    to,
    lastDay,
    revBase,
    group,
    filters,
    currency,
    spend,
    zones,
    kinds,
    bars,
    daily,
    notes,
    drr,
    skuRows,
    options,
    rows,
    totals,
    groupDef,
    isFiltering,
    setPeriod,
    clearFilters,
  }
}
