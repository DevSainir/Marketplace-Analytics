<script setup>
/**
 * One cell of the «По артикулам» table — rendered from the description
 * `pnlSkuCells.cellOf` builds.
 *
 * The figure, a share in brackets (logistics, profit), «N причин» before
 * penalties and, on a size row, a bar of its share of the article. Under the
 * «Продажи, шт» and «Продажи» columns: you can see which size carries the
 * article without reading the numbers.
 *
 * «N причин» only reports the click (`reasons`); the table owns the card — why
 * is written in `PnlPenaltyReasons`.
 */
import { computed } from 'vue'

import { plural } from '@/core/utils/format'

const props = defineProps({
  /** @type {{text: string, cls?: string, sub?: string, subCls?: string, reasons?: object[], bar?: number}} */
  cell: { type: Object, required: true },
})

defineEmits(['reasons'])

const count = computed(() => props.cell.reasons?.length ?? 0)
</script>

<template>
  <button
    v-if="count"
    type="button"
    class="pnl-penalty-more"
    data-testid="penalty-reasons"
    @click.stop="$emit('reasons', $event.currentTarget)"
  >
    {{ count }} {{ plural(count, ['причина', 'причины', 'причин']) }}
  </button>
  <span :class="cell.cls">{{ cell.text }}</span>
  <span v-if="cell.sub" class="text-tiny" :class="cell.subCls"> ({{ cell.sub }})</span>
  <span v-if="cell.bar !== undefined" class="pnl-size-bar" aria-hidden="true">
    <span :style="{ width: `${Math.round(cell.bar * 100)}%` }"></span>
  </span>
</template>
