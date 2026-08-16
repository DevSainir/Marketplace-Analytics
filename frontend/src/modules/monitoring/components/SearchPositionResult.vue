<script setup>
import { formatNumber } from '@/core/utils/format'

/**
 * One probe's outcome: where the SKU stood, or that it did not stand anywhere
 * inside the scanned depth.
 *
 * Split out of `SkuPositionPanel` when that hit its 250-line ceiling. This is
 * the piece with the least to do with the panel's structure — it renders a
 * single response object and emits one intent — while the panel keeps the
 * controls, the pins and the states around them.
 *
 * The two branches must stay distinguishable: a number is a rank, and a null
 * position means "not inside the scanned depth", which is printed together with
 * how deep the scan actually reached. Collapsing them into «нет в выдаче» would
 * claim WB does not carry the card at all — a different and usually false thing.
 */
defineProps({
  /** Backend `SkuSearchPositionResponse`. */
  position: { type: Object, required: true },
  /** A newer probe is already running, so re-checking again would queue noise. */
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['recheck'])

/** «14.08.2026, 15:42» — the probe is a sample, so its timestamp is part of it. */
const checkedAt = (iso) =>
  new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
</script>

<template>
  <div class="mt-md rounded-card border border-border-subtle bg-surface p-lg shadow-card">
    <div class="flex flex-wrap items-baseline justify-between gap-sm">
      <p class="text-base text-primary">
        <template v-if="position.position">
          Позиция в выдаче по «{{ position.query }}»:
          <span class="text-h3 font-bold">{{ position.position }}</span>
          <span class="text-tiny font-medium text-muted">
            (стр. {{ position.page }}, {{ position.position_on_page }})
          </span>
        </template>
        <template v-else>
          Артикул не найден в первых {{ formatNumber(position.positions_scanned) }} позициях по «{{
            position.query
          }}».
          <span v-if="position.truncated" class="text-muted">
            Глубже проверка не заходит — WB ограничивает выдачу.
          </span>
        </template>
      </p>
      <button
        type="button"
        class="rounded-btn border border-border-subtle px-md py-xs text-tiny font-medium text-primary transition hover:bg-canvas disabled:opacity-50"
        :disabled="busy"
        @click="emit('recheck', position.query)"
      >
        Проверить заново
      </button>
    </div>
    <p class="mt-xs text-tiny font-medium text-muted">
      Проверено {{ checkedAt(position.checked_at) }} · всего по запросу
      {{ formatNumber(position.total_found) }} товаров
      <span v-if="position.normalized_query"> · запрос WB: «{{ position.normalized_query }}»</span>
    </p>
    <p v-if="position.other_skus.length" class="mt-sm text-tiny text-muted">
      Другие ваши артикулы в этой выдаче:
      <span v-for="(other, index) in position.other_skus" :key="other.nm_id">
        <span v-if="index">, </span>{{ other.vendor_code || other.nm_id }} — {{ other.position }}
      </span>
    </p>
  </div>
</template>
