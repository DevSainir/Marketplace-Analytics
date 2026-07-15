<script setup>
/**
 * The SHARED «Размер» panel of the two-day stock comparison: one narrow card
 * listing the union of both days' sizes, rendered once to the left of the two
 * day tables (which drop their own size columns via `hideSizeColumn`).
 *
 * Row alignment across the three cards is guaranteed by construction: this
 * panel mirrors StockBreakdownTable's structure (two header rows, one row per
 * size, a totals footer) and declares the SAME explicit row heights.
 */
const props = defineProps({
  /** Union of both days' sizes: `[{chrt_id, tech_size}]`, display order. */
  sizes: { type: Array, required: true },
})

/** Human size label; falls back to the raw `chrt_id` until synced. */
function sizeLabel(size) {
  return size.tech_size ?? `chrt ${size.chrt_id}`
}
</script>

<template>
  <div class="app-datatable">
    <table>
      <thead>
        <tr>
          <th aria-hidden="true"></th>
        </tr>
        <tr>
          <th>Размер</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="size in props.sizes" :key="size.chrt_id">
          <td class="font-medium">{{ sizeLabel(size) }}</td>
        </tr>
      </tbody>
      <tfoot>
        <tr>
          <td class="font-medium">Всего</td>
        </tr>
      </tfoot>
    </table>
  </div>
</template>

<style scoped>
table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
}

/* The SAME explicit heights/paddings as StockBreakdownTable's compact grid —
   the whole point of this panel is pixel-aligned rows across the cards. */
thead th {
  height: 26px;
  padding: 4px 8px;
  font-size: 10px;
  background: #f1f1f1;
}
tbody td {
  height: 24px;
  padding: 3px 8px;
  font-size: 11px;
  background: #f1f1f1;
  white-space: nowrap;
}
tfoot td {
  height: 26px;
  padding: 3px 8px;
  font-size: 11px;
  border-top: 2px solid #e0e0e0;
  background: #f1f1f1;
  white-space: nowrap;
}
</style>
