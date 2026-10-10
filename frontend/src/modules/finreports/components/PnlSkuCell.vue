<script setup>
/**
 * Одна ячейка таблицы «По артикулам» — по описанию из `pnlSkuCells.cellOf`.
 *
 * Цифра, доля в скобках (логистика, прибыль), строки причин под штрафами и у
 * размера — полоска его доли в артикуле. Под колонками «Продажи, шт» и
 * «Продажи»: видно, какой размер тянет артикул, не читая цифр.
 */
defineProps({
  /** @type {{text: string, cls?: string, sub?: string, subCls?: string, lines?: string[], bar?: number}} */
  cell: { type: Object, required: true },
})
</script>

<template>
  <span :class="cell.cls">{{ cell.text }}</span>
  <span v-if="cell.sub" class="text-tiny" :class="cell.subCls"> ({{ cell.sub }})</span>
  <div v-for="line in cell.lines ?? []" :key="line" class="text-micro leading-tight text-muted">
    {{ line }}
  </div>
  <span v-if="cell.bar !== undefined" class="pnl-size-bar" aria-hidden="true">
    <span :style="{ width: `${Math.round(cell.bar * 100)}%` }"></span>
  </span>
</template>
