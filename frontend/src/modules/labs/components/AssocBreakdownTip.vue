<script setup>
/**
 * The associative-conversion breakdown behind a carts/orders cell.
 *
 * Those cells show a campaign's ALL-VARIANT total. This reports the ASSOCIATED
 * share — what the campaign delivered onto other size/colour variants — and
 * names them. It is a hover, not an always-visible column, because the
 * breakdown is interesting for a handful of cells and would clutter thousands.
 *
 * Teleported to `<body>` with fixed coordinates so the table's scroll container
 * cannot clip it; the parent decides the coordinates and whether to flip it
 * above the cell (near the viewport floor a downward list runs off-screen).
 */
import { vFitInside } from '@/core/utils/tipFit'

defineProps({
  /**
   * @type {{x: number, y: number, above: boolean, associated: string,
   *   exact: boolean, skus: Array<{key, label, count, isViewed}>} | null}
   */
  tip: { type: Object, default: null },
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="tip"
      v-fit-inside="tip.area"
      class="fixed z-50 w-72 rounded-card border border-border-subtle bg-surface px-sm py-xs text-tiny leading-snug text-primary shadow-card"
      :style="{
        left: `${tip.x}px`,
        top: `${tip.y}px`,
        transform: tip.above ? 'translateY(-100%)' : null,
      }"
      role="tooltip"
    >
      <!-- The count never wraps away from its dash onto a line of its own. -->
      <p class="text-muted">
        Общее количество ассоциативных конверсий<span class="whitespace-nowrap">
          — <span class="font-semibold text-primary">{{ tip.associated }}</span></span
        >
      </p>

      <!-- Every variant behind the cell. The viewed SKU carries the action
         accent, so its own row reads apart from the associated ones — which
         are the rows that sum to the count above. -->
      <ul v-if="tip.skus.length" class="mt-xs space-y-0.5">
        <li
          v-for="sku in tip.skus"
          :key="sku.key"
          class="flex items-baseline justify-between gap-sm"
          :class="sku.isViewed ? 'font-semibold text-action' : 'text-primary'"
        >
          <span class="truncate">{{ sku.label }}</span>
          <span class="flex-none tabular-nums">{{ sku.count }}</span>
        </li>
      </ul>

      <!-- A two-zone campaign's associated variants are apportioned between
         the zones — WB attributes them per campaign, never per zone. -->
      <p v-if="tip.skus.length && !tip.exact" class="mt-xs text-muted">
        Разбивка по артикулам в этой зоне показов — оценочная.
      </p>
    </div>
  </Teleport>
</template>
