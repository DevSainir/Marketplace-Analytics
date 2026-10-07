<script setup>
/**
 * The per-article (or subject, or brand) money as a ranked list — the kit's
 * «ранжированный список с инлайн-полоской и одной цифрой вместо таблицы».
 *
 * Largest spend first, ten at a time; each row is its name, a `--fact` bar at
 * the scale of the largest row, the money, and ДРР — `--hot` past the alarm.
 * «Итого» of the whole filter heads the list. The full table, with orders,
 * sales, bonus and sorting by any column, is the level below (the section
 * opens it); this list is what a reader needs before asking for it.
 *
 * One projection for every width: a container query moves the bar under the
 * name when the column is narrow, so a phone gets the same list, not a second one.
 */
import { computed, ref, watch } from 'vue'

import DataState from '@/core/components/DataState.vue'
import { formatSku } from '@/core/utils/format'
import { DRR_ALARM, ratioPct, shortMoney } from '@/modules/labs/advertising/adsFormat'

const props = defineProps({
  /** `groupRows` output. */
  rows: { type: Array, required: true },
  /** `totalRow` of the same rows. */
  total: { type: Object, required: true },
  currency: { type: String, default: '' },
  showDrr: { type: Boolean, default: true },
})

const PAGE = 10
const shown = ref(PAGE)

// A new filter or grain is a new list — start it from the top again.
watch(
  () => props.rows,
  () => {
    shown.value = PAGE
  },
)

const sorted = computed(() => [...props.rows].sort((a, b) => b.spend - a.spend))
const visible = computed(() => sorted.value.slice(0, shown.value))
const max = computed(() => Math.max(1, ...props.rows.map((row) => row.spend)))

const money = (value) => shortMoney(value, props.currency)
const drr = (row) => (props.showDrr ? ratioPct(row.drr) : '—')
const hot = (row) => props.showDrr && row.drr > DRR_ALARM
const width = (row) => `${Math.max(0, (100 * row.spend) / max.value).toFixed(2)}%`
</script>

<template>
  <div class="rank" role="list">
    <div class="row head" aria-hidden="true">
      <span class="name" />
      <span class="bar blank" />
      <span class="money">реклама</span>
      <span class="drr">ДРР</span>
    </div>
    <div class="row total" role="listitem">
      <span class="name">Итого {{ rows.length }}</span>
      <span class="bar blank" />
      <span class="money num-m">{{ money(total.spend) }}</span>
      <span class="drr" :class="{ neg: hot(total) }">{{ drr(total) }}</span>
    </div>

    <DataState v-if="!rows.length" kind="empty" layout="bare" text="Ничего не найдено" />
    <div
      v-for="row in visible"
      :key="row.label"
      class="row"
      role="listitem"
      :title="`${formatSku(row.label)}: ${money(row.spend)} · доля ${ratioPct(row.share)}`"
    >
      <span class="name">
        {{ formatSku(row.label) }}
        <small v-if="row.n">· {{ row.n }}</small>
        <small v-else-if="row.subject && row.subject !== '—'">· {{ row.subject }}</small>
      </span>
      <span class="bar"><i :style="{ width: width(row) }" /></span>
      <span class="money num-m">{{ money(row.spend) }}</span>
      <span class="drr" :class="{ neg: hot(row) }">{{ drr(row) }}</span>
    </div>

    <div v-if="shown < rows.length" class="more">
      <button type="button" class="link-btn" @click="shown += PAGE">
        Ещё {{ Math.min(PAGE, rows.length - shown) }} из {{ rows.length - shown }}
      </button>
    </div>
  </div>
</template>
