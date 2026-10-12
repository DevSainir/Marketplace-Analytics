<script setup>
/**
 * Одна ячейка таблицы «По артикулам» — по описанию из `pnlSkuCells.cellOf`.
 *
 * Цифра, доля в скобках (логистика, прибыль), «N причин» перед штрафами и у
 * размера — полоска его доли в артикуле. Под колонками «Продажи, шт» и
 * «Продажи»: видно, какой размер тянет артикул, не читая цифр.
 *
 * «N причин» только сообщает о клике (`reasons`); карточку держит таблица —
 * почему, написано в `PnlPenaltyReasons`.
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
