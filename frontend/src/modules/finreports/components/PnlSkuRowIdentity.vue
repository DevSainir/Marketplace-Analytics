<script setup>
/**
 * The first (frozen) cell of the report: the sizes triangle, the photo and the
 * article.
 *
 * The triangle lives here and not in a column of its own: the table scrolls
 * sideways across twenty money columns, and an expander in its own column would
 * drift away from the row it opens. The photo is here for the same reason — a
 * picture that has drifted away from its article stops identifying it.
 *
 * The «no cost» mark sits here for the same reason: the «Себестоимость»
 * column is fourteen columns to the right, off screen on most laptops, and a
 * mark nobody scrolls to marks nothing.
 */
import SkuThumb from '@/core/components/SkuThumb.vue'

defineProps({
  /** @type {object} A flat table row. */
  row: { type: Object, required: true },
  open: { type: Boolean, default: false },
  /** The mark is a button that asks for the cost, not just a label. */
  canEnterCost: { type: Boolean, default: false },
})

defineEmits(['toggle', 'cost'])
</script>

<template>
  <span class="flex items-center gap-sm">
    <button
      v-if="row.isSku"
      type="button"
      class="pnl-expander"
      :aria-expanded="open"
      :title="open ? 'Свернуть размеры' : 'Показать размеры'"
      @click="$emit('toggle')"
    >
      <span class="inline-block transition" :class="open && 'rotate-90'">▶</span>
    </button>
    <!-- The account-level row and sum rows (subject, brand, group) do not
         expand: they have neither an article nor sizes. -->
    <span v-else class="w-4"></span>

    <SkuThumb v-if="row.isSku" :src="row.photoUrl" :label="row.saName" size="sm" />
    <span :class="row.isBucket ? 'text-muted' : 'font-medium text-primary'">{{ row.saName }}</span>
    <span v-if="row.isGroup" class="text-muted">· {{ row.n }}</span>
    <template v-if="row.uncosted">
      <button
        v-if="canEnterCost"
        type="button"
        class="ui-badge is-warn transition hover:bg-status-warning/20"
        data-testid="enter-cost"
        @click.stop="$emit('cost')"
      >
        + себестоимость
      </button>
      <span v-else class="ui-badge is-warn">нет себестоимости</span>
    </template>
  </span>
</template>
