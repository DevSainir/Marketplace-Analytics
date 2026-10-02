<script setup>
/**
 * What the «Общая» CTR cell divides.
 *
 * That column's «Показы» are advertising показы (WB reports no organic ones),
 * while its «Клики» are the funnel's — organic included. The CTR is the
 * advertising one, so dividing the two rows on screen gives a number that
 * never happened. This names the advertising clicks the CTR actually uses.
 *
 * Teleported and placed like AssocBreakdownTip, by the same delegated hover.
 */
defineProps({
  /** @type {{x: number, y: number, above: boolean, clicks: string, views: string, ctr: string} | null} */
  tip: { type: Object, default: null },
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="tip"
      class="fixed z-50 w-72 rounded-card border border-border-subtle bg-surface px-sm py-xs text-tiny leading-snug text-primary shadow-card"
      :style="{
        left: `${tip.x}px`,
        top: `${tip.y}px`,
        transform: tip.above ? 'translateY(-100%)' : null,
      }"
      role="tooltip"
    >
      <p class="text-muted">CTR рекламы</p>
      <p class="mt-xs tabular-nums">
        <span class="font-semibold">{{ tip.clicks }}</span> кликов /
        <span class="font-semibold">{{ tip.views }}</span> показов =
        <span class="font-semibold">{{ tip.ctr }}</span>
      </p>
      <p class="mt-xs text-muted">В строке «Клики» — все клики, вместе с органикой.</p>
    </div>
  </Teleport>
</template>
