<script setup>
/**
 * A sized ECharts canvas: an option object in, a chart out. Nothing domain.
 *
 * ECharts is imported through `echarts/core` with only the pieces the app
 * actually draws registered — the barrel `import * as echarts from 'echarts'`
 * pulls every chart type, map and toolbox into the bundle (~1 MB) for the two
 * series types we use.
 *
 * The instance is deliberately NOT a `ref`: it is a canvas controller with its
 * own internal mutable state, and making it reactive would have Vue walk that
 * whole graph on every frame.
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { BarChart, FunnelChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

// Registration is the whole point of the `echarts/core` entry point: anything
// left out here is silently absent at runtime — an option referencing it logs
// «Component X is used but not imported» to the console and simply does not
// draw. Add to this list when a chart starts using a new component.
echarts.use([
  BarChart,
  FunnelChart,
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
])

const props = defineProps({
  /** A complete ECharts option (see `chartOptions.js` for the app's theme). */
  option: { type: Object, required: true },
  /** Any CSS length; the canvas fills the width of its container. */
  height: { type: String, default: '340px' },
})

const root = ref(null)
let chart = null
let observer = null

/**
 * `notMerge` because a slide change swaps the whole option: merging would keep
 * the previous chart's extra series alive under the new one's legend.
 */
function render() {
  chart?.setOption(props.option, { notMerge: true })
}

onMounted(() => {
  chart = echarts.init(root.value)
  render()
  // The panel is inside a flex/grid card, so a window resize is not the only
  // thing that changes its width — the element itself is what to watch.
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(() => chart?.resize())
    observer.observe(root.value)
  }
})

watch(() => props.option, render)

onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="root" class="w-full" :style="{ height }" />
</template>
