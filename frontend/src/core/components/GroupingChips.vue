<script setup>
/**
 * «Артикулы · Предметы · Бренды · Группы» — how a table or a chart is cut.
 *
 * One row of chips for every page that cuts by these: the summary's bars, the
 * P&L and balance tables, advertising and the heatmap. It sits at the top right
 * of the block it cuts, outside it — the summary's place, and now everyone's —
 * so a seller finds it where they found it on the last page.
 *
 * `groups` is off for a caller the server will not show groups to (see
 * `GroupsFilter`): a chip that can only ever produce «Без группы» is a broken
 * one.
 */
defineProps({
  modelValue: { type: String, required: true },
  groups: { type: Boolean, default: true },
})
const emit = defineEmits(['update:modelValue'])

const CUTS = [
  { key: 'sku', label: 'Артикулы' },
  { key: 'subject', label: 'Предметы' },
  { key: 'brand', label: 'Бренды' },
  { key: 'group', label: 'Группы' },
]
</script>

<template>
  <div class="flex flex-wrap items-center gap-xs" role="group" aria-label="Группировка">
    <button
      v-for="cut in CUTS.filter((c) => groups || c.key !== 'group')"
      :key="cut.key"
      type="button"
      class="ui-chip"
      :class="{ 'is-on': modelValue === cut.key }"
      :aria-pressed="modelValue === cut.key"
      @click="emit('update:modelValue', cut.key)"
    >
      {{ cut.label }}
    </button>
  </div>
</template>
