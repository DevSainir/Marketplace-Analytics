<script setup>
/**
 * The carousel's chrome: the tab strip, the two arrows, and the slide's title.
 *
 * The tab strip doubles as the position indicator — with a dozen saved
 * questions, stepping to «Расходы по типам» one press at a time would be
 * absurd, so the tabs are both the map and the control.
 *
 * It owns the tab buttons' refs so focus can follow an arrow-key selection
 * (the ARIA tabs pattern); the panel drives that through `focusActiveTab`.
 */
import { ref } from 'vue'

defineProps({
  /** @type {Array<{key: string, tab: string, title: string}>} */
  charts: { type: Array, required: true },
  activeIndex: { type: Number, required: true },
  title: { type: String, default: '' },
})

const emit = defineEmits(['select', 'step'])

const tabRefs = ref([])

/** Move focus onto the selected tab — see the panel's arrow-key handler. */
function focusActiveTab(index) {
  tabRefs.value[index]?.focus()
}

defineExpose({ focusActiveTab })
</script>

<template>
  <div>
    <!-- Scrolls sideways on a narrow screen instead of wrapping into three
         ragged rows. -->
    <div role="tablist" aria-label="Графики метрик" class="flex gap-xs overflow-x-auto pb-xs">
      <button
        v-for="(chart, index) in charts"
        :key="chart.key"
        :ref="(el) => (tabRefs[index] = el)"
        type="button"
        role="tab"
        :aria-selected="index === activeIndex"
        :tabindex="index === activeIndex ? 0 : -1"
        class="shrink-0 rounded-btn px-md py-xs text-tiny font-medium transition phone:py-sm"
        :class="
          index === activeIndex
            ? 'bg-action text-white shadow-soft'
            : 'text-muted hover:bg-hover hover:text-primary'
        "
        @click="emit('select', index)"
      >
        {{ chart.tab }}
      </button>
    </div>

    <div class="mt-md flex items-center gap-sm">
      <button
        type="button"
        class="flex h-8 w-8 shrink-0 items-center justify-center rounded-btn border border-border-subtle bg-canvas text-h3 leading-none text-primary transition hover:bg-hover phone:h-10 phone:w-10"
        aria-label="Предыдущий график"
        @click="emit('step', -1)"
      >
        ‹
      </button>
      <h3 class="min-w-0 flex-1 text-center text-base font-semibold text-primary">{{ title }}</h3>
      <button
        type="button"
        class="flex h-8 w-8 shrink-0 items-center justify-center rounded-btn border border-border-subtle bg-canvas text-h3 leading-none text-primary transition hover:bg-hover phone:h-10 phone:w-10"
        aria-label="Следующий график"
        @click="emit('step', 1)"
      >
        ›
      </button>
    </div>
  </div>
</template>
