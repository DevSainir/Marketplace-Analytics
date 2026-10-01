<script setup>
import { computed } from 'vue'

import { hueVar } from '@/modules/labs/stockRibbonModel'

/**
 * Which colour is which warehouse — the key the three «Остатки» redesigns
 * share, because in all of them a warehouse is a colour inside a size's row
 * rather than a column with its name over it.
 *
 * One warehouse gets no key at all, just its name: a legend of one entry is a
 * label pretending to be a legend. Past the coloured slots the tail folds into
 * «прочие», named by count.
 */
const props = defineProps({
  /** Ranked `{name, hue}` from `buildStockRibbon`. */
  warehouses: { type: Array, required: true },
})

const solo = computed(() => props.warehouses.length === 1)
const coloured = computed(() => props.warehouses.filter((w) => w.hue !== null))
const others = computed(() => props.warehouses.length - coloured.value.length)
</script>

<template>
  <ul class="flex flex-wrap items-center gap-xs" aria-label="Склады">
    <li v-if="solo" class="key">
      <i :style="{ background: hueVar(null, true) }" />
      {{ warehouses[0].name }} — единственный склад
    </li>
    <template v-else>
      <li v-for="wh in coloured" :key="wh.name" class="key">
        <i :style="{ background: hueVar(wh.hue, false) }" />{{ wh.name }}
      </li>
      <li v-if="others" class="key is-other">
        <i :style="{ background: hueVar(null, false) }" />прочие · {{ others }}
      </li>
    </template>
    <slot />
  </ul>
</template>

<style scoped>
.key {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px 3px 8px;
  border-radius: 999px;
  background: var(--ui-surface);
  box-shadow: var(--ui-sh-xs);
  font-size: 11.5px;
  font-weight: 500;
  color: var(--ui-ink);
  white-space: nowrap;
}
.key i {
  width: 8px;
  height: 8px;
  border-radius: 999px;
}
.key.is-other {
  color: var(--ui-muted);
}
</style>
