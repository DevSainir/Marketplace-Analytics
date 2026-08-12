<script setup>
/**
 * The cost-price grid as rows — the phone projection of `CostPriceTable`.
 *
 * Unlike the other phone lists on this page, nothing folds away: the row's whole
 * point is the number you type into it, so the input stays on screen and there
 * is no disclosure. What the desktop spends columns on — nm_id, units settled,
 * the source of the figure — collapses onto the second line, which is metadata
 * you read, not data you act on.
 *
 * Uncosted rows keep their warning tint. The grid exists to make the *gaps* as
 * visible as the entries (see `CostPriceGrid`), and that is the one signal a
 * narrower screen must not lose.
 *
 * Dumb by contract: the parent owns the draft buffer and the save.
 */
import { computed, ref, watch } from 'vue'

import { formatNumber } from '@/core/utils/format'

const props = defineProps({
  /** @type {Array<object>} Rows from `CostPriceGrid`, uncosted first by volume. */
  rows: { type: Array, default: () => [] },
  /** Reads the current draft (or stored) value of a row. */
  value: { type: Function, required: true },
  saving: { type: Boolean, default: false },
})

const emit = defineEmits(['input', 'remove'])

const SOURCE_LABELS = { seed: 'со слов продавца', manual: 'вручную' }

/** How many rows to show; «Показать ещё» grows it. Edits on rows scrolled past
 *  stay in the parent's draft and still save — the pending count says so. */
const PAGE = 10
const shown = ref(PAGE)
watch(
  () => props.rows,
  () => {
    shown.value = PAGE
  },
)

const visible = computed(() => props.rows.slice(0, shown.value))
</script>

<template>
  <!-- The card the desktop table wears is on the <table>'s own wrapper, which is
       hidden here — so the row list carries its own, or it sits bare on the
       canvas (design-system «The plane»). -->
  <div class="rounded-card border border-border-subtle bg-surface p-md shadow-card">
    <ul class="record-list">
      <li
        v-for="row in visible"
        :key="row.nmId"
        class="record-card"
        :class="row.stored === null && 'bg-status-warning/5'"
      >
        <div class="record-line">
          <div class="record-main">
            <span class="record-title">{{ row.vendorCode || '—' }}</span>
            <span class="record-sub">
              {{ row.nmId }} · {{ formatNumber(row.soldUnits) }} шт
              <template v-if="SOURCE_LABELS[row.source]">
                · {{ SOURCE_LABELS[row.source] }}
              </template>
            </span>
          </div>

          <div class="flex flex-none flex-col items-end gap-xs">
            <input
              type="number"
              min="0"
              step="1"
              inputmode="decimal"
              :aria-label="`Себестоимость ${row.vendorCode || row.nmId}`"
              class="h-11 w-24 rounded-input border border-border-subtle bg-canvas px-sm text-right tabular-nums text-primary focus:border-action focus:outline-none"
              :value="value(row)"
              :placeholder="row.stored === null ? 'не задана' : ''"
              @input="emit('input', row, $event.target.value)"
            />
            <button
              v-if="row.stored !== null"
              type="button"
              class="rounded-btn px-xs text-tiny font-medium text-muted transition hover:text-status-negative"
              :disabled="saving"
              @click="emit('remove', row.nmId)"
            >
              Очистить
            </button>
          </div>
        </div>
      </li>

      <li v-if="!rows.length" class="record-card">
        <p class="py-xl text-center text-base text-muted">Нет проданных SKU за последний год.</p>
      </li>
    </ul>

    <button
      v-if="shown < rows.length"
      type="button"
      class="mt-sm min-h-11 w-full rounded-btn border border-border-subtle bg-surface text-base font-medium text-primary transition hover:border-action hover:text-action"
      @click="shown += PAGE"
    >
      Показать ещё ({{ rows.length - shown }})
    </button>
  </div>
</template>

<style scoped src="./styles/RecordCards.css"></style>
