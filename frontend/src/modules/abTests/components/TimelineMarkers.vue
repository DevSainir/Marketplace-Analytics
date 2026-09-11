<script setup>
/**
 * The thumbnails hanging off the timeline's ticks — one row of them.
 *
 * A component rather than a `v-for` written twice because the markers sit on
 * **both** sides of the track: they alternate above and below so that two of
 * them can never be closer than every other tick, which is what makes it
 * possible to label every turn rather than only the ones with room. The parent
 * decides which half goes where; this only knows how to draw a row.
 *
 * `large` is the parent's answer to "does this line have room": a test with a
 * handful of turns should show them at a size where a photo is a photo, and one
 * with a hundred cannot. Sizing is not something a row can decide for itself —
 * both rows have to agree, or the track sits crooked between them.
 */
defineProps({
  /** Segments to label, each carrying `leftPercent`, `label` and `variantId`. */
  segments: { type: Array, default: () => [] },
  /** variant_id -> object URL for the stored original. */
  imageUrls: { type: Object, default: () => ({}) },
  /** True when the row hangs above the track rather than below it. */
  above: { type: Boolean, default: false },
  /** True on a line short enough to give every photo more room. */
  large: { type: Boolean, default: false },
})
</script>

<template>
  <div class="ab-markers" :class="{ 'ab-markers--above': above, 'ab-markers--large': large }">
    <div
      v-for="segment in segments"
      :key="segment.key"
      class="ab-markers__item"
      :style="{ left: `${segment.leftPercent}%` }"
      data-testid="timeline-marker"
    >
      <img
        v-if="imageUrls[segment.variantId]"
        :src="imageUrls[segment.variantId]"
        :alt="segment.label"
        class="ab-markers__thumb"
      />
      <div v-else class="ab-markers__thumb ab-markers__thumb--empty"></div>
      <span class="ab-markers__caption">{{ segment.label }}</span>
    </div>
  </div>
</template>

<style scoped src="@/modules/abTests/components/styles/TimelineMarkers.css"></style>
