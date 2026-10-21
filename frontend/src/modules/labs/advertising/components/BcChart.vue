<script setup>
/**
 * The kit's `BC.seriesChart` as a component: options in, the kit's SVG out.
 *
 * The kit draws at a fixed pixel width so that its axis labels stay 11.5px
 * instead of scaling with the picture — "draw to the actual width of the column,
 * not of the page". So the width is measured here and the chart is redrawn
 * whenever the column changes, not just on a window resize.
 *
 * `v-html` is safe for this string: every label and value the kit writes into
 * it goes through its own `esc`, and the colours are the caller's tokens.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { BC } from '@/modules/labs/advertising/bold/charts'

const props = defineProps({
  /** Everything `BC.seriesChart` takes except `W`. */
  options: { type: Object, required: true },
})

const box = ref(null)
const width = ref(0)
let observer = null

onMounted(() => {
  observer = new ResizeObserver(([entry]) => {
    width.value = Math.round(entry.contentRect.width)
  })
  observer.observe(box.value)
})
onBeforeUnmount(() => observer?.disconnect())

const html = computed(() =>
  width.value ? BC.seriesChart({ ...props.options, W: width.value }) : '',
)
</script>

<template>
  <div ref="box" v-html="html" />
</template>
