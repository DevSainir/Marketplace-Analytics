<script setup>
/**
 * What the "Overall" CTR cell divides.
 *
 * That column's "Impressions" are advertising views (WB reports no organic
 * ones), while its "Clicks" are the funnel's — organic included. The CTR is the
 * advertising one, so dividing the two rows on screen gives a number that
 * never happened. This names the advertising clicks the CTR actually uses.
 *
 * Teleported and placed like AssocBreakdownTip, by the same delegated hover.
 */
import { plural } from '@/core/utils/format'
import { vFitInside } from '@/core/utils/tipFit'

defineProps({
  /**
   * @type {{x: number, y: number, above: boolean, clicks: string, views: string,
   *   clickCount: number, viewCount: number, ctr: string} | null}
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
      <p class="text-muted">Ad CTR</p>
      <p class="mt-xs tabular-nums">
        <span class="font-semibold">{{ tip.clicks }}</span>
        {{ plural(tip.clickCount, ['click', 'clicks']) }} /
        <span class="font-semibold">{{ tip.views }}</span>
        {{ plural(tip.viewCount, ['impression', 'impressions']) }} =
        <span class="font-semibold">{{ tip.ctr }}</span>
      </p>
      <p class="mt-xs text-muted">The "Clicks" row counts every click, organic included.</p>
    </div>
  </Teleport>
</template>
