<script setup>
/**
 * The metric chips above a chart, in the groups the caller hands it.
 *
 * The groups carry NO behaviour — they are where a reader looks for a metric,
 * nothing more. What the chart treats differently is the unit (metrics sharing
 * one share an axis) and the mark. Laid out in one row so all three are
 * readable at a glance rather than a wall to scan.
 *
 * The mode switch sits with them because it is a property of this chart, not a
 * caption: rebasing to 100 at the first day is the documented answer to metrics
 * whose scales do not fit together, offered rather than forced.
 *
 * Dumb by contract: groups in, selection and mode out.
 */
const props = defineProps({
  /** @type {Array<{title: string, items: Array<{key: string, name: string}>}>} */
  groups: { type: Array, required: true },
  /** @type {Array<{key: string, label: string}>} */
  modes: { type: Array, default: () => [] },
  /** Selected metric keys, in the order they were ticked. */
  modelValue: { type: Array, default: () => [] },
  mode: { type: String, default: 'absolute' },
})

const emit = defineEmits(['update:modelValue', 'update:mode'])

/** Toggle one metric, preserving the order the others were added in. */
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
        <p class="mb-xs text-micro font-medium uppercase tracking-wide text-muted">
          {{ group.title }}
        </p>
        <ul class="flex flex-wrap gap-xs">
          <li v-for="item in group.items" :key="item.key">
            <button
              type="button"
              :aria-pressed="modelValue.includes(item.key)"
              class="rounded-btn border px-sm py-1 text-tiny font-medium transition"
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

      <div v-if="modes.length" class="ml-auto flex shrink-0 gap-xs">
        <button
          v-for="option in modes"
          :key="option.key"
          type="button"
          :aria-pressed="mode === option.key"
          class="rounded-btn px-sm py-1 text-tiny font-medium transition"
          :class="
            mode === option.key
              ? 'bg-action text-white'
              : 'text-muted hover:bg-hover hover:text-primary'
          "
          @click="emit('update:mode', option.key)"
        >
          {{ option.label }}
        </button>
      </div>
    </div>

    <p v-if="!modelValue.length" class="py-xl text-center text-base text-muted">
      Выберите метрики, которые хотите сравнить на одном графике.
    </p>
  </div>
</template>
