<script setup>
/**
 * The metric chips above a chart, in the groups the caller hands it.
 *
 * The groups carry NO behaviour — they are where a reader looks for a metric,
 * nothing more, and the chart repeats the same split in its hover so the two
 * agree. Laid out in one row so all three are readable at a glance rather than
 * a wall to scan.
 *
 * Dumb by contract: groups in, selection out.
 */
const props = defineProps({
  /** @type {Array<{title: string, items: Array<{key: string, name: string}>}>} */
  groups: { type: Array, required: true },
  /** Selected metric keys; the chart sorts them back into catalogue order. */
  modelValue: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue'])

/** Toggle one metric. */
function toggle(key) {
  emit(
    'update:modelValue',
    props.modelValue.includes(key)
      ? props.modelValue.filter((entry) => entry !== key)
      : [...props.modelValue, key],
  )
}
</script>

<template>
  <div>
    <!-- One row, three columns: `flex-1 min-w-0` lets each group shrink to
         share the width and wrap its own chips, instead of the widest group
         pushing the others onto their own lines. Below `sm` they stack. -->
    <div class="flex flex-wrap items-start gap-lg">
      <div v-for="group in groups" :key="group.title" class="min-w-0 flex-1 sm:basis-0">
        <p class="mb-xs text-tiny font-semibold uppercase tracking-wide text-muted">
          {{ group.title }}
        </p>
        <ul class="flex flex-wrap gap-xs">
          <li v-for="item in group.items" :key="item.key">
            <button
              type="button"
              :aria-pressed="modelValue.includes(item.key)"
              class="rounded-btn border px-sm py-1 text-base font-medium transition"
              :class="
                modelValue.includes(item.key)
                  ? 'border-action bg-action text-white'
                  : 'border-border-subtle text-muted hover:bg-hover hover:text-primary'
              "
              @click="toggle(item.key)"
            >
              {{ item.name }}
            </button>
          </li>
        </ul>
      </div>
    </div>

    <p v-if="!modelValue.length" class="py-xl text-center text-base text-muted">
      Выберите метрики, которые хотите сравнить на одном графике.
    </p>
  </div>
</template>
